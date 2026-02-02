import { ECSClient, RunTaskCommand } from "@aws-sdk/client-ecs";
import { DynamoDBClient, PutItemCommand, QueryCommand } from "@aws-sdk/client-dynamodb";
import { v4 as uuidv4 } from 'uuid';

const ecs = new ECSClient({});
const ddb = new DynamoDBClient({});

// Constants for configuration
const MAX_SESSIONS_PER_USER = parseInt(process.env.MAX_SESSIONS_PER_USER || '5');
const SESSION_TTL_HOURS = parseInt(process.env.SESSION_TTL_HOURS || '1');
const DEFAULT_USER = 'anonymous';

interface APIGatewayEvent {
  headers: Record<string, string | undefined>;
  body?: string;
}

interface StartResponse {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
}

/**
 * Validates the authorization header
 */
const validateAuth = (authHeader?: string): string => {
  if (!authHeader) {
    return DEFAULT_USER;
  }

  // Basic validation for Bearer token format
  if (authHeader.startsWith('Bearer ')) {
    const token = authHeader.substring(7);
    // In a real implementation, you would verify the JWT here
    // For now, we'll just return a user ID derived from the token
    return `user_${token.substring(0, 8)}`;
  }

  // For basic auth or other schemes
  return `user_${authHeader.substring(0, 8)}`;
};

/**
 * Checks if the user has exceeded the maximum number of active sessions
 */
const checkUserQuota = async (userId: string): Promise<boolean> => {
  if (!process.env.TABLE_NAME) {
    throw new Error('TABLE_NAME environment variable is not set');
  }

  const params = {
    TableName: process.env.TABLE_NAME,
    IndexName: 'UserIndex', // Assuming we have a GSI on the user attribute
    KeyConditionExpression: 'user = :user',
    ExpressionAttributeValues: {
      ':user': { S: userId }
    }
  };

  try {
    const result = await ddb.send(new QueryCommand(params));
    const activeSessions = result.Count || 0;
    
    return activeSessions < MAX_SESSIONS_PER_USER;
  } catch (error) {
    console.error('Error checking user quota:', error);
    // Fail open in case of DynamoDB error to avoid denial of service
    return true;
  }
};

export const handler = async (event: APIGatewayEvent): Promise<StartResponse> => {
  console.log('Start shell session request received:', JSON.stringify(event.headers, null, 2));

  try {
    // Validate environment variables
    if (!process.env.CLUSTER_NAME || !process.env.TASK_DEF_ARN || !process.env.TABLE_NAME) {
      console.error('Missing required environment variables');
      return {
        statusCode: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: 'Internal server error: Missing configuration' 
        })
      };
    }

    // 1. Parse and validate User
    const userId = validateAuth(event.headers.Authorization);
    
    // Check user quota
    const hasQuota = await checkUserQuota(userId);
    if (!hasQuota) {
      console.warn(`User ${userId} exceeded session quota`);
      return {
        statusCode: 429,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: `Maximum sessions exceeded (${MAX_SESSIONS_PER_USER})` 
        })
      };
    }

    const sessionId = uuidv4();
    const ttlTimestamp = Math.floor(Date.now() / 1000) + (SESSION_TTL_HOURS * 3600);

    // 2. Run Fargate Task
    const runTask = await ecs.send(new RunTaskCommand({
      cluster: process.env.CLUSTER_NAME,
      taskDefinition: process.env.TASK_DEF_ARN,
      launchType: "FARGATE",
      enableExecuteCommand: true, // Crucial for interactive shell
      networkConfiguration: {
        awsvpcConfiguration: {
          subnets: [process.env.SUBNET_ID!],
          securityGroups: [process.env.SECURITY_GROUP_ID!],
          assignPublicIp: "DISABLED"
        }
      }
    }));

    const taskArn = runTask.tasks?.[0]?.taskArn;
    if (!taskArn) {
      console.error('Failed to start container - no task ARN returned');
      return {
        statusCode: 500,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Failed to start container" 
        })
      };
    }

    // 3. Save Session to DB with TTL
    await ddb.send(new PutItemCommand({
      TableName: process.env.TABLE_NAME,
      Item: {
        sessionId: { S: sessionId },
        taskArn: { S: taskArn },
        user: { S: userId },
        createdAt: { N: Math.floor(Date.now() / 1000).toString() },
        ttl: { N: ttlTimestamp.toString() }
      }
    }));

    console.log(`Session ${sessionId} created for user ${userId}`);

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ 
        sessionId, 
        status: "initializing",
        message: "Shell session started successfully"
      })
    };
  } catch (error: any) {
    console.error('Error in start handler:', error);
    
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ 
        error: error.message || 'Internal server error' 
      })
    };
  }
};