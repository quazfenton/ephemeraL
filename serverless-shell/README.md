# Serverless Shell Implementation

This project implements a serverless shell solution using AWS CDK with TypeScript, Lambda functions, DynamoDB, and ECS Fargate. It allows users to start, execute commands in, and stop shell environments securely.

## Architecture

- **API Gateway**: REST endpoints for shell operations
- **Lambda Functions**: Business logic for start/execute/stop operations
- **DynamoDB**: Session management with TTL for automatic cleanup
- **ECS Fargate**: Containerized shell environments
- **Docker**: Container image with necessary CLI tools

## Features

- Secure shell execution in isolated containers
- Session management with automatic cleanup
- Input sanitization to prevent command injection
- JWT authentication support
- Resource quotas to prevent abuse
- Comprehensive logging and monitoring
- Rate limiting and security controls

## Prerequisites

- Node.js 18+
- AWS CLI configured with appropriate permissions
- Docker
- AWS CDK CLI (`npm install -g aws-cdk`)

## Setup

1. Install dependencies:
```bash
npm install
```

2. Bootstrap CDK (if not already done):
```bash
cdk bootstrap
```

3. Deploy the infrastructure:
```bash
npx cdk deploy
```

## Endpoints

- `POST /shell/start`: Start a new shell session
- `POST /shell/execute`: Execute a command in the shell
- `POST /shell/stop`: Stop the shell session

## Environment Variables

The application uses the following environment variables:

- `MAX_SESSIONS_PER_USER`: Maximum concurrent sessions per user (default: 5)
- `SESSION_TTL_HOURS`: Session time-to-live in hours (default: 1)

## Security

- Authentication via JWT tokens
- Input sanitization to prevent command injection
- Resource quotas to limit concurrent sessions
- Isolated containers for each user session
- Encrypted DynamoDB storage
- VPC-secured Lambda functions
- Minimal IAM permissions

## Frontend Integration

The execute endpoint returns an SSM Session object containing a WebSocket URL. The frontend must use a WebSocket client to connect to the streamUrl provided in the response. Use libraries like `aws-ssm-session-manager-js` to handle the WebSocket connection.

## Running Tests

1. Install dev dependencies:
```bash
npm install
```

2. Run all tests:
```bash
npm test
```

3. Run tests in watch mode:
```bash
npm run test:watch
```

4. Generate coverage report:
```bash
npm run test:coverage
```

## Development

1. Build the project:
```bash
npm run build
```

2. Watch for changes:
```bash
npm run watch
```

## Optimization Strategies

- Consider using Fargate Spot instances to reduce costs
- Implement warm pools for faster startup times
- Add monitoring and alerting for operational visibility
- Use CloudWatch alarms for key metrics
- Implement request/response logging for debugging

## Deployment

The infrastructure is defined in `lib/shell-backend-stack.ts` using AWS CDK. The stack includes:

- VPC with public and private subnets
- ECS cluster with container insights
- DynamoDB table with encryption and point-in-time recovery
- API Gateway with logging and CORS
- Lambda functions with security configurations
- IAM roles with minimal required permissions
- CloudWatch logs for monitoring