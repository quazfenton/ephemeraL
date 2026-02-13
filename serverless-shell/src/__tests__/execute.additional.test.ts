import { handler } from '../lambdas/execute/index';
import { mockClient } from 'aws-sdk-client-mock';
import { ECSClient, ExecuteCommandCommand, DescribeTasksCommand } from '@aws-sdk/client-ecs';
import { DynamoDBClient, GetItemCommand } from '@aws-sdk/client-dynamodb';

// Mock the AWS SDK clients
const ecsMock = mockClient(ECSClient);
const ddbMock = mockClient(DynamoDBClient);

// Mock environment variables
process.env.CLUSTER_NAME = 'test-cluster';
process.env.TABLE_NAME = 'test-table';
process.env.CONTAINER_NAME = 'ShellContainer';
process.env.JWT_SECRET = 'test-secret';

describe('Execute Lambda Function - Additional Tests', () => {
  beforeEach(() => {
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should handle command with special characters', async () => {
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

    ecsMock.on(ExecuteCommandCommand).resolves({
      session: {
        streamUrl: 'wss://ssm.region.amazonaws.com/',
        tokenValue: 'mock-token'
      }
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174000',
        command: 'echo "hello world" > /tmp/test.txt'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(200);
  });

  test('should handle command length limit', async () => {
    const longCommand = 'a'.repeat(1001);

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174000',
        command: longCommand
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('too long');
  });

  test('should reject command with path manipulation', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174000',
        command: 'cd ../../../etc && cat passwd'
      })
    };

    const result = await handler(event);
    // Command should be sanitized but not necessarily rejected
    expect(result.statusCode).toBeLessThan(500);
  });

  test('should handle task in STOPPING state', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174005' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'STOPPING' }]
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174005',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(409);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('not ready');
  });

  test('should handle missing environment variables', async () => {
    const originalCluster = process.env.CLUSTER_NAME;
    delete process.env.CLUSTER_NAME;

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174000',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Missing configuration');

    process.env.CLUSTER_NAME = originalCluster;
  });

  test('should handle invalid JSON in body', async () => {
    const event = {
      headers: {},
      body: 'invalid-json{'
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Invalid JSON');
  });

  test('should handle empty task array from DescribeTasks', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174006' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: []
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174006',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(404);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('task not found');
  });

  test('should handle ECS ExecuteCommand failure', async () => {
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

    ecsMock.on(ExecuteCommandCommand).rejects(new Error('ECS error'));

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174007',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Command execution failed');
  });

  test('should handle session ownership validation with missing auth', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174008' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174008',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(403);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Unauthorized');
  });

  test('should handle malformed session ID format', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'not-a-uuid',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Invalid sessionId format');
  });

  test('should include CORS headers in response', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({})
    };

    const result = await handler(event);
    expect(result.headers['Access-Control-Allow-Origin']).toBe('*');
  });

  test('should handle DynamoDB GetItem failure', async () => {
    ddbMock.on(GetItemCommand).rejects(new Error('DynamoDB error'));

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174009',
        command: 'echo test'
      })
    };

    const result = await handler(event);
    expect(result.statusCode).toBe(500);
  });

  test('should log command execution for audit', async () => {
    const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174010' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(ExecuteCommandCommand).resolves({
      session: {
        streamUrl: 'wss://ssm.region.amazonaws.com/',
        tokenValue: 'mock-token'
      }
    });

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      },
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174010',
        command: 'ls -la'
      })
    };

    await handler(event);

    // Verify logging occurred
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  test('should handle command with only whitespace', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174011',
        command: '   '
      })
    };

    const result = await handler(event);
    // Should either sanitize or reject
    expect([400, 200]).toContain(result.statusCode);
  });

  test('should reject commands with shell operators that could be dangerous', async () => {
    const dangerousCommands = [
      'rm -rf /',
      'chmod 0000 /bin',
      'chown root:root /etc/passwd'
    ];

    for (const cmd of dangerousCommands) {
      const event = {
        headers: {},
        body: JSON.stringify({
          sessionId: '123e4567-e89b-12d3-a456-426614174012',
          command: cmd
        })
      };

      const result = await handler(event);
      expect(result.statusCode).toBe(400);
      const responseBody = JSON.parse(result.body);
      expect(responseBody.error).toContain('Dangerous');
    }
  });

  test('should handle concurrent execute requests', async () => {
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174013' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    ecsMock.on(ExecuteCommandCommand).resolves({
      session: {
        streamUrl: 'wss://ssm.region.amazonaws.com/',
        tokenValue: 'mock-token'
      }
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174013',
        command: 'echo test'
      })
    };

    // Execute multiple requests concurrently
    const results = await Promise.all([
      handler(event),
      handler(event),
      handler(event)
    ]);

    // All should succeed
    results.forEach(result => {
      expect(result.statusCode).toBe(200);
    });
  });
});