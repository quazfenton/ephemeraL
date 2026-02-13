import { handler } from '../lambdas/stop/index';
import { mockClient } from 'aws-sdk-client-mock';
import { ECSClient, StopTaskCommand, DescribeTasksCommand } from '@aws-sdk/client-ecs';
import { DynamoDBClient, GetItemCommand, DeleteItemCommand } from '@aws-sdk/client-dynamodb';

const ecsMock = mockClient(ECSClient);
const ddbMock = mockClient(DynamoDBClient);

process.env.CLUSTER_NAME = 'test-cluster';
process.env.TABLE_NAME = 'test-table';
process.env.JWT_SECRET = 'test-secret';

describe('Stop Lambda Function - Additional Tests', () => {
  beforeEach(() => {
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should sanitize authorization header in logs', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174000' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer secret-token'
      },
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174000'
      })
    };

    await handler(event);

    const logCalls = consoleSpy.mock.calls.map(call => JSON.stringify(call));
    const hasRedactedAuth = logCalls.some(call => call.includes('[REDACTED]'));
    const hasActualToken = logCalls.some(call => call.includes('secret-token'));

    expect(hasRedactedAuth).toBe(true);
    expect(hasActualToken).toBe(false);

    consoleSpy.mockRestore();
  });

  test('should handle malformed UUID format', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'not-a-valid-uuid'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Invalid sessionId format');
  });

  test('should include CORS headers', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({})
    };

    const result = await handler(event);
    expect(result.headers['Access-Control-Allow-Origin']).toBe('*');
  });

  test('should handle session ownership validation', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174001' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'other-user' }
      }
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174001'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(403);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Unauthorized');
  });

  test('should delete session even if task stop fails', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174002' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).rejects(new Error('ECS stop failed'));
    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174002'
      })
    };

    const result = await handler(event);

    // Should still succeed because session is deleted
    expect(result.statusCode).toBe(200);
  });

  test('should handle task in DELETED state', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174003' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'DELETED' }]
    });

    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174003'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);

    // Verify StopTaskCommand was not called
    const stopCalls = ecsMock.commandCalls(StopTaskCommand);
    expect(stopCalls.length).toBe(0);
  });

  test('should handle DynamoDB DeleteItem failure', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174004' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).resolves({});
    ddbMock.on(DeleteItemCommand).rejects(new Error('DynamoDB delete failed'));

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174004'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
  });

  test('should handle invalid JSON in body', async () => {
    const event = {
      headers: {},
      body: 'invalid{json'
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Invalid JSON');
  });

  test('should handle missing environment variables', async () => {
    const originalCluster = process.env.CLUSTER_NAME;
    delete process.env.CLUSTER_NAME;

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174005'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Missing configuration');

    process.env.CLUSTER_NAME = originalCluster;
  });

  test('should log session termination', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174006' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).resolves({});
    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174006'
      })
    };

    await handler(event);

    const logCalls = consoleSpy.mock.calls.map(call => call.join(' '));
    const hasTerminationLog = logCalls.some(call => call.includes('terminated'));

    expect(hasTerminationLog).toBe(true);
    consoleSpy.mockRestore();
  });

  test('should return terminated status', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174007' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).resolves({});
    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174007'
      })
    };

    const result = await handler(event);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('terminated');
  });

  test('should handle concurrent stop requests', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174008' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(StopTaskCommand).resolves({});
    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174008'
      })
    };

    // Execute multiple stop requests concurrently
    const results = await Promise.all([
      handler(event),
      handler(event),
      handler(event)
    ]);

    // All should succeed (idempotent)
    results.forEach(result => {
      expect([200, 404]).toContain(result.statusCode);
    });
  });

  test('should handle task ARN extraction from session', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174009' },
        taskArn: { S: 'arn:aws:ecs:us-east-1:123456789:task/cluster-name/abc123' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    let capturedTaskArn: string | undefined;
    ecsMock.on(StopTaskCommand).callsFake((input) => {
      capturedTaskArn = input.task;
      return {};
    });

    ddbMock.on(DeleteItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174009'
      })
    };

    await handler(event);

    expect(capturedTaskArn).toBe('arn:aws:ecs:us-east-1:123456789:task/cluster-name/abc123');
  });
});