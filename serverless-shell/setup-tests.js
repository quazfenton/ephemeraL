// setup-tests.js
// Setup file for Jest tests

// Mock the console to suppress logs during tests unless DEBUG is enabled
if (!process.env.DEBUG) {
  console.log = jest.fn();
  console.warn = jest.fn();
  console.error = jest.fn();
}

// Set up global environment variables for tests
process.env.CLUSTER_NAME = process.env.CLUSTER_NAME || 'test-cluster';
process.env.TASK_DEF_ARN = process.env.TASK_DEF_ARN || 'arn:aws:ecs:region:account:task-definition:test:1';
process.env.TABLE_NAME = process.env.TABLE_NAME || 'test-table';
process.env.CONTAINER_NAME = process.env.CONTAINER_NAME || 'ShellContainer';
process.env.SUBNET_ID = process.env.SUBNET_ID || 'subnet-test';
process.env.SECURITY_GROUP_ID = process.env.SECURITY_GROUP_ID || 'sg-test';
process.env.MAX_SESSIONS_PER_USER = process.env.MAX_SESSIONS_PER_USER || '5';
process.env.SESSION_TTL_HOURS = process.env.SESSION_TTL_HOURS || '1';