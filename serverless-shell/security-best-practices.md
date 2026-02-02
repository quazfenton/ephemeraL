# Security Considerations & Best Practices

## Authentication & Authorization

### JWT Middleware Implementation
For production environments, implement JWT authentication using API Gateway authorizers:

```typescript
// In CDK stack
const authorizer = new apigateway.CfnAuthorizer(this, 'APIGatewayAuthorizer', {
  restApiId: api.restApiId,
  name: 'JWTAuthorizer',
  type: 'COGNITO_USER_POOLS', // Or REQUEST for custom lambda authorizer
  identitySource: 'method.request.header.Authorization',
  providerArns: [userPoolArn], // Your Cognito User Pool ARN
});
```

### Session Quotas
Implement user-specific quotas to prevent resource exhaustion:

```typescript
// In start lambda - before creating new session
const userSessions = await getUserActiveSessions(user);
if (userSessions.length >= MAX_SESSIONS_PER_USER) {
  return {
    statusCode: 429,
    body: JSON.stringify({ error: "Maximum sessions exceeded" })
  };
}
```

## Input Validation & Sanitization

### Enhanced Command Sanitization
The basic sanitization in the execute function should be expanded:

```typescript
const sanitizeCommand = (command: string): string => {
  // Block dangerous characters/sequences
  const dangerousPatterns = [
    /rm\s+-rf/,
    /chmod\s+\d{4}/,
    /chown\s+/,
    /\$\(.*\)/,  // Command substitution
    /`.*`/,      // Backtick command substitution
  ];
  
  for (const pattern of dangerousPatterns) {
    if (pattern.test(command)) {
      throw new Error("Dangerous command detected");
    }
  }
  
  // Only allow alphanumeric and safe characters
  return command.replace(/[^a-zA-Z0-9\s\/\-\_\.\~\&\|\>\<\=\+\:\@\$\!\*\(\)\[\]\{\}\,]/g, '');
};
```

## Resource Management

### Concurrency Controls
Implement proper resource limits:

```typescript
// In start lambda
const totalActiveSessions = await getActiveSessionsCount();
const maxConcurrentSessions = parseInt(process.env.MAX_CONCURRENT_SESSIONS || '50');

if (totalActiveSessions >= maxConcurrentSessions) {
  return {
    statusCode: 503,
    body: JSON.stringify({ error: "Service temporarily unavailable" })
  };
}
```

### Session Timeout
Enhance session management with configurable timeouts:

```typescript
// In DynamoDB table creation
const ttlSeconds = parseInt(process.env.SESSION_TTL_SECONDS || '3600'); // 1 hour default
const ttlTimestamp = Math.floor(Date.now() / 1000) + ttlSeconds;

await ddb.send(new PutItemCommand({
  TableName: process.env.TABLE_NAME,
  Item: {
    sessionId: { S: sessionId },
    taskArn: { S: taskArn },
    user: { S: user },
    createdAt: { N: Math.floor(Date.now() / 1000).toString() },
    ttl: { N: ttlTimestamp.toString() }
  }
}));
```

## Monitoring & Observability

### CloudWatch Alarms
Set up monitoring for key metrics:

```typescript
// Add to CDK stack
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';

const alarmTopic = new sns.Topic(this, 'ShellAlarmTopic');

// Alarm for high error rates
const errorRateMetric = new cloudwatch.MathExpression({
  expression: '100*(errors/invocations)',
  usingMetrics: {
    invocations: startFn.metricInvocations(),
    errors: startFn.metricErrors()
  },
  label: 'Error Rate (%)'
});

const errorRateAlarm = new cloudwatch.Alarm(this, 'HighErrorRateAlarm', {
  metric: errorRateMetric,
  threshold: 5,
  evaluationPeriods: 2,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  alarmDescription: 'Triggers when error rate exceeds 5%'
});

errorRateAlarm.addAlarmAction(new actions.SnsAction(alarmTopic));
```

## Cost Optimization

### Fargate Spot Instances
Use spot pricing for cost savings:

```typescript
// In task definition
const taskDefinition = new ecs.FargateTaskDefinition(this, 'ShellTaskDef', {
  cpu: 256,
  memoryLimitMiB: 512,
  runtimePlatform: {
    cpuArchitecture: ecs.CpuArchitecture.X86_64,
    operatingSystemFamily: ecs.OperatingSystemFamily.LINUX
  }
});

// In run task command
const runTask = await ecs.send(new RunTaskCommand({
  // ... other properties
  capacityProviderStrategy: [{
    capacityProvider: 'FARGATE_SPOT',
    weight: 1
  }]
}));
```

### Container Optimization
Optimize the Docker image for size and security:

```dockerfile
FROM ubuntu:22.04

# Install minimal packages needed
RUN apt-get update && apt-get install -y \
    curl \
    git \
    jq \
    vim \
    iputils-ping \
    python3 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user with limited permissions
RUN groupadd -r shellgroup && useradd -r -g shellgroup -m shelluser
USER shelluser
WORKDIR /home/shelluser

# Run with minimal privileges
CMD ["tail", "-f", "/dev/null"]
```

## Error Handling & Recovery

### Graceful Degradation
Handle service limits gracefully:

```typescript
// In execute lambda
try {
  // ... execute command logic
} catch (error: any) {
  if (error.name === 'LimitExceededException') {
    return {
      statusCode: 429,
      body: JSON.stringify({ 
        error: "Resource limit exceeded, please try again later" 
      })
    };
  }
  
  console.error('Execute command failed:', error);
  return {
    statusCode: 500,
    body: JSON.stringify({ error: "Command execution failed" })
  };
}
```

## Compliance & Audit

### Logging & Auditing
Ensure proper audit trails:

```typescript
// In execute lambda - log command execution
console.log(JSON.stringify({
  level: 'INFO',
  message: 'Command executed',
  userId: user,
  sessionId: sessionId,
  command: safeCommand,
  timestamp: new Date().toISOString()
}));
```

These security measures and best practices should be implemented based on your specific compliance requirements and risk tolerance.