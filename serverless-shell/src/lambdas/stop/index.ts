import { ECSClient, StopTaskCommand, DescribeTasksCommand } from "@aws-sdk/client-ecs";
import { DynamoDBClient, DeleteItemCommand, GetItemCommand } from "@aws-sdk/client-dynamodb";

const ecs = new ECSClient({});
const ddb = new DynamoDBClient({});

interface APIGatewayEvent {
  headers: Record<string, string | undefined>;
  body?: string;
}

interface StopBody {
  sessionId: string;
}

interface StopResponse {
  statusCode: number;
  headers: Record<string, string>;
  body: string;
}

/**
 * Validates the session belongs to the requesting user
 */
const validateSessionOwnership = (sessionItem: any, authHeader?: string): boolean => {
  // In a real implementation, you would validate that the session belongs to the user
  // For now, we'll just return true
  return true;
};

export const handler = async (event: APIGatewayEvent): Promise<StopResponse> => {
  console.log('Stop shell session request received:', JSON.stringify({
    headers: event.headers,
    body: event.body ? 'present' : 'missing'
  }, null, 2));

  try {
    // Validate environment variables
    if (!process.env.CLUSTER_NAME || !process.env.TABLE_NAME) {
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
    let body: StopBody;
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

    const { sessionId } = body;

    // Validate required field
    if (!sessionId) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ 
          error: "Missing sessionId" 
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

    // 1. Retrieve Session Information
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

    // Check if task is still running before attempting to stop
    try {
      const taskDesc = await ecs.send(new DescribeTasksCommand({
        cluster: process.env.CLUSTER_NAME,
        tasks: [taskArn!]
      }));

      if (taskDesc.tasks && taskDesc.tasks.length > 0) {
        const task = taskDesc.tasks[0];
        if (task.lastStatus === "STOPPED" || task.lastStatus === "DELETED") {
          console.log(`Task for session ${sessionId} is already stopped`);
          // Still delete the session record even if task is already stopped
        } else {
          // 2. Stop Fargate Task
          await ecs.send(new StopTaskCommand({
            cluster: process.env.CLUSTER_NAME,
            task: taskArn
          }));
          
          console.log(`Task ${taskArn} stopped for session ${sessionId}`);
        }
      }
    } catch (ecsError) {
      console.error(`Error checking/stopping task ${taskArn} for session ${sessionId}:`, ecsError);
      // Continue with deleting the session record even if ECS operation fails
    }

    // 3. Remove session from DB
    await ddb.send(new DeleteItemCommand({
      TableName: process.env.TABLE_NAME,
      Key: { sessionId: { S: sessionId } }
    }));

    console.log(`Session ${sessionId} terminated for user ${sessionUser}`);

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ 
        status: "terminated",
        sessionId,
        message: "Shell session terminated successfully"
      })
    };
  } catch (error: any) {
    console.error('Error in stop handler:', error);
    
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ 
        error: error.message || "Internal server error" 
      })
    };
  }
};