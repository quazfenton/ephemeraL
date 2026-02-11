import { handler } from '../lambdas/start/index';
import { mockClient } from 'aws-sdk-client-mock';
import { ECSClient, RunTaskCommand, RunTaskCommandOutput } from '@aws-sdk/client-ecs';
import { DynamoDBClient, PutItemCommand } from '@aws-sdk/client-dynamodb';
import { mock } from 'jest-mock-extended';

// Mock the AWS SDK clients
const ecsMock = mockClient(ECSClient);
const ddbMock = mockClient(DynamoDBClient);

// Mock environment variables
process.env.CLUSTER_NAME = 'test-cluster';
process.env.TASK_DEF_ARN = 'arn:aws:ecs:region:account:task-definition:test:1';
process.env.TABLE_NAME = 'test-table';
process.env.CONTAINER_NAME = 'ShellContainer';
process.env.SUBNET_ID = 'subnet-test';
process.env.SECURITY_GROUP_ID = 'sg-test';

describe('Start Lambda Function', () => {
  beforeEach(() => {
    // Reset mocks before each test
    ecsMock.reset();
    ddbMock.reset();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  test('should start a new shell session successfully', async () => {
    // Mock ECS run task response
    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    // Mock DynamoDB put item response
    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.status).toBe('initializing');
    expect(responseBody.sessionId).toBeDefined();
    expect(typeof responseBody.sessionId).toBe('string');
    expect(responseBody.sessionId.split('-')).toHaveLength(5); // UUID format
  });

  test('should handle ECS run task failure', async () => {
    // Mock ECS run task failure
    ecsMock.on(RunTaskCommand).resolves({
      tasks: []
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

  test('should handle DynamoDB error gracefully', async () => {
    // Mock ECS run task success
    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    // Mock DynamoDB put item failure
    ddbMock.on(PutItemCommand).rejects(new Error('DynamoDB error'));

    const event = {
      headers: {
        Authorization: 'Bearer test-token'
      }
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(500);
    const responseBody = JSON.parse(result.body);
    expect(responseBody.error).toBe('DynamoDB error');
  });

  test('should use anonymous user when no auth header is provided', async () => {
    // Mock ECS run task response
    ecsMock.on(RunTaskCommand).resolves({
      tasks: [{ taskArn: 'arn:aws:ecs:region:account:task/task-id' }]
    } as RunTaskCommandOutput);

    // Mock DynamoDB put item response
    ddbMock.on(PutItemCommand).resolves({});

    const event = {
      headers: {}
    };

    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    // The function should proceed without throwing an error
  });

  test('should return error when required environment variables are missing', async () => {
    // Temporarily remove an environment variable
    const originalClusterName = process.env.CLUSTER_NAME;
    delete process.env.CLUSTER_NAME;

    try {
      const event = {
        headers: {
          Authorization: 'Bearer test-token'
        }
      };

      const result = await handler(event);

      expect(result.statusCode).toBe(500);
      const responseBody = JSON.parse(result.body);
      expect(responseBody.error).toBe('Internal server error: Missing configuration');
    } finally {
      // Restore the environment variable even if the test fails
      process.env.CLUSTER_NAME = originalClusterName;
    }
  });
});