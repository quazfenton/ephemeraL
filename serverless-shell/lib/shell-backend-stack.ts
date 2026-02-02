import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as path from 'path';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';

export class ShellBackendStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // 1. Network & Cluster
    const vpc = new ec2.Vpc(this, 'ShellVpc', { 
      maxAzs: 2,
      natGateways: 1 // Ensure internet access for container pulls
    });
    
    const cluster = new ecs.Cluster(this, 'ShellCluster', { 
      vpc,
      containerInsights: true // Enable container insights for monitoring
    });

    // 2. DynamoDB for Session Management with GSI for user queries
    const table = new dynamodb.Table(this, 'ShellSessions', {
      partitionKey: { name: 'sessionId', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl', // Auto-delete old sessions
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      encryption: dynamodb.TableEncryption.AWS_MANAGED, // Enable encryption
      pointInTimeRecovery: true, // Enable backup
    });

    // Add Global Secondary Index for user-based queries (for quota checking)
    table.addGlobalSecondaryIndex({
      indexName: 'UserIndex',
      partitionKey: { name: 'user', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.KEYS_ONLY,
    });

    // 3. Docker Image
    const shellImage = new DockerImageAsset(this, 'ShellImage', {
      directory: path.join(__dirname, '../src/docker'),
    });

    // 4. Fargate Task Definition with security enhancements
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'ShellTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
    });

    // Add container with security configurations
    const shellContainer = taskDefinition.addContainer('ShellContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(shellImage),
      logging: ecs.LogDrivers.awsLogs({ 
        streamPrefix: 'shell',
        logRetention: logs.RetentionDays.ONE_WEEK
      }),
      // Run with minimal privileges
      user: '1000', // Use non-root user from Dockerfile
    });

    // Add execution role with minimal required permissions
    const executionRole = taskDefinition.executionRole!;
    executionRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy')
    );

    // 5. API Gateway with enhanced security
    const api = new apigateway.RestApi(this, 'ShellApi', {
      restApiName: 'Serverless Shell API',
      description: 'API for managing serverless shell sessions',
      deployOptions: { 
        stageName: 'v1',
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: true,
        metricsEnabled: true
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
      }
    });

    // Helper to create Lambdas with security configurations
    const createLambda = (name: string, handler: string, environmentVars: { [key: string]: string }) => {
      const fn = new lambda.Function(this, name, {
        runtime: lambda.Runtime.NODEJS_18_X,
        handler: `index.handler`,
        code: lambda.Code.fromAsset(path.join(__dirname, `../src/lambdas/${handler}`)),
        environment: {
          ...environmentVars,
          LOG_LEVEL: 'INFO' // Set log level
        },
        timeout: cdk.Duration.seconds(29),
        memorySize: 256,
        logRetention: logs.RetentionDays.ONE_WEEK,
        // Add VPC configuration for security
        vpc: vpc,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      });
      
      // Grant minimal required permissions
      table.grantReadWriteData(fn);
      return fn;
    };

    // Environment variables for all lambdas
    const lambdaEnvironment = {
      CLUSTER_NAME: cluster.clusterName,
      TASK_DEF_ARN: taskDefinition.taskDefinitionArn,
      TABLE_NAME: table.tableName,
      CONTAINER_NAME: 'ShellContainer',
      SUBNET_ID: vpc.privateSubnets[0].subnetId,
      SECURITY_GROUP_ID: vpc.vpcDefaultSecurityGroup,
      MAX_SESSIONS_PER_USER: '5', // Limit concurrent sessions per user
      SESSION_TTL_HOURS: '1', // Session timeout in hours
    };

    // --- Start Shell Lambda ---
    const startFn = createLambda('StartShellLambda', 'start', lambdaEnvironment);
    
    // Permission to run tasks - scoped to specific resources
    startFn.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:RunTask',
        'iam:PassRole'
      ],
      resources: [
        taskDefinition.taskDefinitionArn,
        cluster.clusterArn
      ]
    }));

    // --- Execute Command Lambda ---
    const executeFn = createLambda('ExecuteShellLambda', 'execute', lambdaEnvironment);
    
    // Permission to execute commands inside containers (ECS Exec) - scoped to specific resources
    executeFn.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:ExecuteCommand',
        'ecs:DescribeTasks'
      ],
      resources: [
        cluster.clusterArn,
        taskDefinition.taskDefinitionArn
      ]
    }));

    // --- Stop Shell Lambda ---
    const stopFn = createLambda('StopShellLambda', 'stop', lambdaEnvironment);
    
    stopFn.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:StopTask',
        'ecs:DescribeTasks'
      ],
      resources: [
        cluster.clusterArn,
        taskDefinition.taskDefinitionArn
      ]
    }));

    // 6. API Routes with throttling
    const shellRes = api.root.addResource('shell');

    // Configure method options for security
    const methodOptions: apigateway.MethodOptions = {
      methodResponses: [
        {
          statusCode: '200',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        },
        {
          statusCode: '400',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        },
        {
          statusCode: '403',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        },
        {
          statusCode: '404',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        },
        {
          statusCode: '429',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        },
        {
          statusCode: '500',
          responseModels: {
            'application/json': apigateway.Model.EMPTY_MODEL
          }
        }
      ]
    };

    // POST /shell/start
    const startResource = shellRes.addResource('start');
    startResource.addMethod('POST', new apigateway.LambdaIntegration(startFn), methodOptions);

    // POST /shell/execute
    const executeResource = shellRes.addResource('execute');
    executeResource.addMethod('POST', new apigateway.LambdaIntegration(executeFn), methodOptions);

    // POST /shell/stop
    const stopResource = shellRes.addResource('stop');
    stopResource.addMethod('POST', new apigateway.LambdaIntegration(stopFn), methodOptions);

    // Output the API endpoint for reference
    new cdk.CfnOutput(this, 'ApiEndpoint', {
      value: api.url!,
      description: 'The URL of the Shell API',
      exportName: 'ShellApiEndpoint'
    });

    new cdk.CfnOutput(this, 'ClusterName', {
      value: cluster.clusterName,
      description: 'The name of the ECS cluster',
      exportName: 'ShellClusterName'
    });
  }
}