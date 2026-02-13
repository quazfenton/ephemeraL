import { handler } from '../lambdas/start/index';
import { mockClient } from 'aws-sdk-client-mock';
import { ECSClient, RunTaskCommand, RunTaskCommandOutput } from '@aws-sdk/client-ecs';
import { DynamoDBClient, PutItemCommand, QueryCommand } from '@aws-sdk/client-dynamodb';

const ecsMock = mockClient(ECSClient);
const ddbMock = mockClient(DynamoDBClient);

process.env.CLUSTER_NAME = 'test-cluster';
process.env.TASK_DEF_ARN = 'arn:aws:ecs:region:account:task-definition:test:1';
process.env.TABLE_NAME = 'test-table';
process.env.CONTAINER_NAME = 'ShellContainer';
process.env.SUBNET_ID = 'subnet-test';
process.env.SECURITY_GROUP_ID = 'sg-test';
process.env.JWT_SECRET = 'test-secret';
process.env.MAX_SESSIONS_PER_USER = '5';
process.env.SESSION_TTL_HOURS = '1';

describe('Start Lambda Function - Additional Tests', () => {
  beforeEach(() => {
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should enforce session quota', async () => {
    // Mock QueryCommand to return max sessions
    ddbMock.on(QueryCommand).resolves({
      Count: 5,
      Items: []
    });

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(429);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Maximum sessions exceeded');
  });

  test('should allow session creation when under quota', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 3,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);
  });

  test('should fail open on DynamoDB quota check error', async () => {
    ddbMock.on(QueryCommand).rejects(new Error('DynamoDB query error'));

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);
    // Should still allow creation (fail open)
    expect(result.statusCode).toBe(200);
  });

  test('should set TTL on session', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    let capturedItem: any;
    ddbMock.on(PutItemCommand).callsFake((input) => {
      capturedItem = input.Item;
      return {};
    });

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    await handler(event);

    // Verify TTL was set
    expect(capturedItem).toHaveProperty('ttl');
    expect(capturedItem.ttl.N).toBeDefined();
  });

  test('should handle ECS RunTask with failures array', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [],
      failures: [{
        arn: 'arn:aws:ecs:region:account:task/task-id',
        reason: 'RESOURCE:CPU'
      }]
    } as RunTaskCommandOutput);

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Failed to start container');
  });

  test('should sanitize auth headers in logs', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer secret-token'
      }
    };

    await handler(event);

    // Check that logs don't contain the actual token
    const logCalls = consoleSpy.mock.calls.map(call => JSON.stringify(call));
    const hasRedactedAuth = logCalls.some(call => call.includes('[REDACTED]'));
    const hasActualToken = logCalls.some(call => call.includes('secret-token'));

    expect(hasRedactedAuth).toBe(true);
    expect(hasActualToken).toBe(false);

    consoleSpy.mockRestore();
  });

  test('should use default user for missing auth', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    let capturedItem: any;
    ddbMock.on(PutItemCommand).callsFake((input) => {
      capturedItem = input.Item;
      return {};
    });

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);

    // Should have used default/anonymous user
    expect(capturedItem.user.S).toBe('anonymous');
  });

  test('should include CORS headers', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.headers['Access-Control-Allow-Origin']).toBe('*');
  });

  test('should handle missing subnet ID', async () => {
    const originalSubnet = process.env.SUBNET_ID;
    delete process.env.SUBNET_ID;

    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);

    process.env.SUBNET_ID = originalSubnet;
  });

  test('should handle missing task definition ARN', async () => {
    const originalTaskDef = process.env.TASK_DEF_ARN;
    delete process.env.TASK_DEF_ARN;

    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Missing configuration');

    process.env.TASK_DEF_ARN = originalTaskDef;
  });

  test('should generate valid UUID for session ID', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);

    const responseBody = JSON.parse(result.body);
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    expect(uuidRegex.test(responseBody.sessionId)).toBe(true);
  });

  test('should save createdAt timestamp', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    let capturedItem: any;
    ddbMock.on(PutItemCommand).callsFake((input) => {
      capturedItem = input.Item;
      return {};
    });

    const event = {
      headers: {}
    };

    await handler(event);

    expect(capturedItem).toHaveProperty('createdAt');
    expect(capturedItem.createdAt.N).toBeDefined();
    const timestamp = parseInt(capturedItem.createdAt.N);
    expect(timestamp).toBeGreaterThan(0);
  });

  test('should handle ECS RunTask exception', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).rejects(new Error('ECS service unavailable'));

    const event = {
      headers: {}
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBeDefined();
  });

  test('should use configured session TTL', async () => {
    process.env.SESSION_TTL_HOURS = '2';

    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    let capturedItem: any;
    ddbMock.on(PutItemCommand).callsFake((input) => {
      capturedItem = input.Item;
      return {};
    });

    const event = {
      headers: {}
    };

    await handler(event);

    const ttl = parseInt(capturedItem.ttl.N);
    const createdAt = parseInt(capturedItem.createdAt.N);
    const ttlDiff = ttl - createdAt;

    // Should be approximately 2 hours (7200 seconds)
    expect(ttlDiff).toBeGreaterThan(7000);
    expect(ttlDiff).toBeLessThan(7400);

    process.env.SESSION_TTL_HOURS = '1';
  });

  test('should enable execute command on task', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    let capturedInput: any;
    ecsMock.on(RunTaskCommand).callsFake((input) => {
      capturedInput = input;
      return {
        tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
      } as RunTaskCommandOutput;
    });

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {}
    };

    await handler(event);

    expect(capturedInput.enableExecuteCommand).toBe(true);
  });

  test('should return initializing status', async () => {
    ddbMock.on(QueryCommand).resolves({
      Count: 0,
      Items: []
    });

    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {}
    };

    const result = await handler(event);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('initializing');
  });
});