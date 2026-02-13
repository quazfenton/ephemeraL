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

describe('Execute Lambda Function', () => {
  beforeEach(() => {
    // Reset mocks before each test
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should execute command successfully', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174000' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response (task is running)
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    // Mock ECS execute command response
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
        sessionId: '123e4567-e89b-12d3-a456-426614174000',
        command: 'echo hello'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('executed');
    expect(responseBody.command).toBe('echo hello');
    expect(responseBody.session).toBeDefined();
  });

  test('should return 400 for missing sessionId or command', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({})
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Missing sessionId or command');
  });

  test('should return 400 for invalid command', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174001',  // Valid UUID format
        command: 'rm -rf /'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toContain('Dangerous command pattern detected');
  });

  test('should return 404 for non-existent session', async () => {
    // Mock DynamoDB get item response (no item found)
    ddbMock.on(GetItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174002',  // Valid UUID format
        command: 'echo test'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(404);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Session not found');
  });

  test('should return 409 when task is not running', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174003' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response (task is not running)
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'PENDING' }]
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174003',  // Valid UUID format
        command: 'echo test'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(409);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Shell is not ready (PENDING). Please wait.');
  });

  test('should sanitize command properly', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: '123e4567-e89b-12d3-a456-426614174004' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response (task is running)
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    // Mock ECS execute command response
    ecsMock.on(ExecuteCommandCommand).resolves({
      session: {
        streamUrl: 'wss://ssm.region.amazonaws.com/',
        tokenValue: 'mock-token'
      }
    });

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: '123e4567-e89b-12d3-a456-426614174004',  // Valid UUID format
        command: 'echo test && dangerous command'
      })
    };

    const result = await handler(event);

    // The command should be sanitized and processed
    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('executed');
    // The sanitized command should not contain the dangerous part
    expect(responseBody.command).not.toContain('dangerous command');
  });

  test('should return 400 for invalid session ID format', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'invalid-session-id',  // This should remain as an invalid format for this test
        command: 'echo test'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Invalid sessionId format');
  });
});