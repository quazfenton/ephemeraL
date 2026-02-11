import { handler } from '../lambdas/stop/index';
import { mockClient } from 'aws-sdk-client-mock';
import { ECSClient, StopTaskCommand, DescribeTasksCommand } from '@aws-sdk/client-ecs';
import { DynamoDBClient, GetItemCommand, DeleteItemCommand } from '@aws-sdk/client-dynamodb';

// Mock the AWS SDK clients
const ecsMock = mockClient(ECSClient);
const ddbMock = mockClient(DynamoDBClient);

// Mock environment variables
process.env.CLUSTER_NAME = 'test-cluster';
process.env.TABLE_NAME = 'test-table';

describe('Stop Lambda Function', () => {
  beforeEach(() => {
    // Reset mocks before each test
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should stop a shell session successfully', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: 'test-session-id' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    // Mock ECS stop task response
    ecsMock.on(StopTaskCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      },
      body: JSON.stringify({
        sessionId: 'test-session-id'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('terminated');
    expect(responseBody.sessionId).toBe('test-session-id');
  });

  test('should handle case where task is already stopped', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: 'test-session-id' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response (task is already stopped)
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'STOPPED' }]
    });

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      },
      body: JSON.stringify({
        sessionId: 'test-session-id'
      })
    };

    const result = await handler(event);

    // Should still succeed even if task is already stopped
    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('terminated');
  });

  test('should return 400 for missing sessionId', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({})
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Missing sessionId');
  });

  test('should return 404 for non-existent session', async () => {
    // Mock DynamoDB get item response (no item found)
    ddbMock.on(GetItemCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'non-existent-session-id'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(404);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Session not found');
  });

  test('should return 400 for invalid session ID format', async () => {
    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'invalid-session-id'
      })
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(400);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('Invalid sessionId format');
  });

  test('should handle ECS describe tasks error gracefully', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: 'test-session-id' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks error
    ecsMock.on(DescribeTasksCommand).rejects(new Error('ECS error'));

    // Mock ECS stop task response (should still try to stop)
    ecsMock.on(StopTaskCommand).resolves({});

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'test-session-id'
      })
    };

    const result = await handler(event);

    // Should still succeed because we continue with deleting the session record
    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('terminated');
  });

  test('should handle ECS stop task error gracefully', async () => {
    // Mock DynamoDB get item response
    ddbMock.on(GetItemCommand).resolves({
      Item: {
        sessionId: { S: 'test-session-id' },
        taskArn: { S: 'arn:aws:ecs:region:account:task/task-id' },
        user: { S: 'test-user' }
      }
    });

    // Mock ECS describe tasks response
    ecsMock.on(DescribeTasksCommand).resolves({
      tasks: [{ lastStatus: 'RUNNING' }]
    });

    // Mock ECS stop task error
    ecsMock.on(StopTaskCommand).rejects(new Error('ECS stop error'));

    const event = {
      headers: {},
      body: JSON.stringify({
        sessionId: 'test-session-id'
      })
    };

    const result = await handler(event);

    // Should still succeed because we continue with deleting the session record
    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('terminated');
  });
});