import { ECSClient, ExecuteCommandCommand, DescribeTasksCommand } from "@aws-sdk/client-ecs";
import { DynamoDBClient, GetItemCommand } from "@aws-sdk/client-dynamodb";
import { verify } from 'jsonwebtoken';

const ecs = new ECSClient({});
const ddb = new DynamoDBClient({});

// Define interfaces for type safety
interface APIGatewayEvent {
  headers: Record<string, string | undefined>;
  body?: string;
}

interface ExecuteBody {
  sessionId: string;
  command: string;
}

interface ExecuteResponse {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
}

/**
 * Validates the input command to prevent dangerous operations
 */
const validateAndSanitizeCommand = (command: string): string => {
  // Trim whitespace
  let sanitized = command.trim();
  
  // Block dangerous patterns
  const dangerousPatterns = [
    /^rm\s+-rf/i,                    // Dangerous rm commands
    /chmod\s+\d{4}/i,                // chmod with 4 digits (could be dangerous)
    /chown\s+/i,                     // chown commands
    /\$\(.*\)/,                      // Command substitution with $()
    /`.*`/,                          // Command substitution with backticks
    /\$\{.*\}/,                      // Parameter expansion with ${...}
    /;\s*rm/i,                       // Semicolon followed by rm
    /&&\s*rm/i,                      // && followed by rm
    /\|\|\s*rm/i,                    // || followed by rm
    /nc\s+\-l/i,                     // Netcat listeners (potential reverse shells)
    /socat\s+/i,                     // Socat (potential reverse shells)
    /python.*\-c/i,                  // Python one-liners
    /perl.*\-e/i,                    // Perl one-liners
    /sh\s+.*<\s*\/dev\/tcp/i,        // Shell redirection to TCP
  ];

  for (const pattern of dangerousPatterns) {
    if (pattern.test(sanitized)) {
      throw new Error(`Dangerous command pattern detected: ${pattern}`);
    }
  }

  // Only allow safe characters in the command
  // Alphanumeric, spaces, common Unix operators, file paths
  if (!/^[\w\s\/\-\_\.\~\&\|\>\<\=\+\:\@\$\!\*\(\)\[\]\{\}\,\;\'\"\`\^]+$/i.test(sanitized)) {
    throw new Error("Command contains invalid characters");
  }

  return sanitized;
};

/**
 * Validates the session belongs to the requesting user
 */
const validateSessionOwnership = (sessionItem: any, authHeader?: string): boolean => {
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return false;
  }

  const token = authHeader.substring(7);

  try {
    // In a real implementation, you would verify the JWT against your identity provider's public key
    // For now, we'll decode it and extract the user ID
    const jwtSecret = process.env.JWT_SECRET;
    if (!jwtSecret) {
      console.error('JWT_SECRET environment variable is not configured');
      return false;
    }
    const decoded: any = verify(token, jwtSecret);
    const userId = decoded.sub || decoded.userId;

    // Compare the authenticated user ID with the session owner
    const sessionUserId = sessionItem.user.S;

    return userId === sessionUserId;
  } catch (error) {
    console.error('Token verification failed:', error);
    return false;
  }
};

export const handler = async (event: APIGatewayEvent): Promise<ExecuteResponse> => {
  console.log('Execute command request received:', JSON.stringify({
    headers: event.headers,
    body: event.body ? 'present' : 'missing'
  }, null, 2));

  try {
    // Validate environment variables
    if (!process.env.CLUSTER_NAME || !process.env.TABLE_NAME || !process.env.CONTAINER_NAME) {
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

    // Parse request body
    let body: ExecuteBody;
    try {
      body = JSON.parse(event.body || "{}");
    } catch (parseError) {
      console.error('Invalid JSON in request body:', parseError);
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Invalid JSON in request body" 
        })
      };
    }

    const { sessionId, command } = body;

    // Validate required fields
    if (!sessionId || !command) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Missing sessionId or command" 
        })
      };
    }

    // Validate session ID format (UUID)
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(sessionId)) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Invalid sessionId format" 
        })
      };
    }

    // Validate and sanitize command
    let safeCommand: string;
    try {
      safeCommand = validateAndSanitizeCommand(command);
    } catch (validationError: any) {
      console.warn(`Command validation failed for session ${sessionId}:`, validationError.message);
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: validationError.message 
        })
      };
    }

    // Limit command length
    if (safeCommand.length > 1000) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Command too long (max 1000 characters)" 
        })
      };
    }

    // 2. Retrieve Session Information
    const sessionResult = await ddb.send(new GetItemCommand({
      TableName: process.env.TABLE_NAME,
      Key: { sessionId: { S: sessionId } }
    }));

    if (!sessionResult.Item) {
      console.warn(`Session not found: ${sessionId}`);
      return {
        statusCode: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Session not found" 
        })
      };
    }

    // Validate session ownership
    if (!validateSessionOwnership(sessionResult.Item, event.headers.Authorization)) {
      console.warn(`Unauthorized access attempt to session: ${sessionId}`);
      return {
        statusCode: 403,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Unauthorized access to session" 
        })
      };
    }

    const taskArn = sessionResult.Item.taskArn.S;
    const sessionUser = sessionResult.Item.user.S;

    // 3. Check Task Status
    const taskDesc = await ecs.send(new DescribeTasksCommand({
      cluster: process.env.CLUSTER_NAME,
      tasks: [taskArn!]
    }));

    if (!taskDesc.tasks || taskDesc.tasks.length === 0) {
      console.error(`Task not found for session ${sessionId}`);
      return {
        statusCode: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Associated task not found" 
        })
      };
    }

    const task = taskDesc.tasks[0];
    if (task.lastStatus !== "RUNNING") {
      console.warn(`Task for session ${sessionId} is not running: ${task.lastStatus}`);
      return {
        statusCode: 409,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: `Shell is not ready (${task.lastStatus}). Please wait.` 
        })
      };
    }

    // Log command execution for audit purposes
    console.log(`Executing command for user ${sessionUser}, session ${sessionId}: ${safeCommand}`);

    // 4. Execute Command via ECS Exec
    const execCmd = await ecs.send(new ExecuteCommandCommand({
      cluster: process.env.CLUSTER_NAME,
      task: taskArn,
      container: process.env.CONTAINER_NAME,
      interactive: true,
      command: ["/bin/sh", "-c", safeCommand]
    }));

    // 5. Return Session Details
    // Note: The actual command output would need to be captured via the SSM session
    // which typically requires a WebSocket connection from the client
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        status: "executed",
        sessionId,
        command: safeCommand,
        session: execCmd.session // Contains streamUrl and token for WebSocket connection
      })
    };
  } catch (error: any) {
    console.error('Error in execute handler:', error);
    
    // Return generic error message to avoid leaking internal details
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ 
        error: "Command execution failed" 
      })
    };
  }
};