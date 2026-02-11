# Cloud Terminal Platform - File Index

This document provides an overview of all files in the project and their purposes.

## Core Code Files

### Python Modules

| File | Description | Key Functions |
|------|-------------|---------------|
| `auth.py` | Authentication and identity management | `get_user_id()`, `map_user_to_workspace()` |
| `snapshot_api.py` | FastAPI REST API for snapshot operations | `/snapshot/create`, `/snapshot/restore`, `/snapshot/list` |

### Shell Scripts

| File | Description | Usage |
|------|-------------|-------|
| `create_snapshot.sh` | Creates filesystem snapshot of user workspace | `./create_snapshot.sh <user_id> <snapshot_id>` |
| `restore_snapshot.sh` | Restores workspace from snapshot | `./restore_snapshot.sh <user_id> <snapshot_id>` |
| `manage_container.sh` | Container lifecycle management | `./manage_container.sh <action> <user_id>` |

## Documentation Files

| File | Description | Content |
|------|-------------|---------|
| `README.md` | Project overview and quick start guide | Architecture, features, basic usage |
| `SETUP_GUIDE.md` | Comprehensive setup instructions | Prerequisites, installation, deployment |
| `data_models.md` | Data structures and architecture | Identity model, snapshot model, flow diagrams |
| `identity_config.md` | Identity provider configuration guide | IdP options, integration examples |
| `FILE_INDEX.md` | This file - index of all project files | File descriptions and purposes |

## Configuration Files

| File | Description | Purpose |
|------|-------------|---------|
| `requirements.txt` | Python package dependencies | FastAPI, jose, pydantic, etc. |
| `.env.example` | Environment variable template | Configuration examples |

## File Structure Overview

```
cloud-terminal-platform/
├── Core Python Modules
│   ├── auth.py                 # JWT authentication
│   └── snapshot_api.py         # REST API endpoints
│
├── Shell Scripts
│   ├── create_snapshot.sh      # Snapshot creation
│   ├── restore_snapshot.sh     # Snapshot restoration
│   └── manage_container.sh     # Container management
│
├── Documentation
│   ├── README.md               # Project overview
│   ├── SETUP_GUIDE.md          # Setup instructions
│   ├── data_models.md          # Data architecture
│   ├── identity_config.md      # Identity setup
│   └── FILE_INDEX.md           # This file
│
└── Configuration
    ├── requirements.txt        # Python dependencies
    └── .env.example            # Environment template
```

## Quick Reference

### Starting the Platform

```bash
# Install dependencies
pip install -r requirements.txt

# Start API server
python snapshot_api.py
```

### Managing Containers

```bash
# Create container
./manage_container.sh create u_123

# Check status
./manage_container.sh status u_123
```

### Snapshot Operations

```bash
# Create snapshot
./create_snapshot.sh u_123 snap_001

# Restore snapshot
./restore_snapshot.sh u_123 snap_001
```

## Code Statistics

- **Python files**: 2
- **Shell scripts**: 3
- **Documentation files**: 5
- **Configuration files**: 2
- **Total files**: 12

## Dependencies

### Python Packages (from requirements.txt)
- fastapi
- uvicorn
- python-jose
- pydantic
- httpx
- python-dotenv

### System Requirements
- Docker
- bash
- zstd
- Python 3.11+

## New Serverless Shell Implementation

### Serverless Shell Files

| File | Description | Key Components |
|------|-------------|----------------|
| `CIDD.md` | Context, Intent, Decision, Done plan | Requirements and implementation plan |
| `serverless-shell/README.md` | Serverless shell overview | Architecture, setup, endpoints |
| `serverless-shell/package.json` | Node.js project dependencies | CDK, SDKs, TypeScript |
| `serverless-shell/tsconfig.json` | TypeScript compiler config | ES2020, strict mode |
| `serverless-shell/lib/shell-backend-stack.ts` | AWS CDK infrastructure | VPC, ECS, DynamoDB, API Gateway |
| `serverless-shell/src/docker/Dockerfile` | Container image definition | Ubuntu base, CLI tools, security |
| `serverless-shell/src/lambdas/start/index.ts` | Start shell session | ECS task creation, session storage |
| `serverless-shell/src/lambdas/execute/index.ts` | Execute commands | ECS Exec, input sanitization |
| `serverless-shell/src/lambdas/stop/index.ts` | Stop shell session | Task termination, cleanup |
| `serverless-shell/security-best-practices.md` | Security guidelines | Authentication, validation, monitoring |

## File Structure Overview (Updated)

```
cloud-terminal-platform/
├── Core Python Modules
│   ├── auth.py                 # JWT authentication
│   └── snapshot_api.py         # REST API endpoints
│
├── Shell Scripts
│   ├── create_snapshot.sh      # Snapshot creation
│   ├── restore_snapshot.sh     # Snapshot restoration
│   └── manage_container.sh     # Container management
│
├── Serverless Shell Implementation
│   ├── README.md               # Overview and setup
│   ├── package.json            # Dependencies
│   ├── tsconfig.json           # TypeScript config
│   ├── lib/
│   │   └── shell-backend-stack.ts # CDK infrastructure
│   ├── src/
│   │   ├── docker/
│   │   │   └── Dockerfile     # Container definition
│   │   └── lambdas/
│   │       ├── start/          # Start session
│   │       ├── execute/        # Execute commands
│   │       └── stop/           # Stop session
│   └── security-best-practices.md # Security guidelines
│
├── Documentation
│   ├── README.md               # Project overview
│   ├── SETUP_GUIDE.md          # Setup instructions
│   ├── data_models.md          # Data architecture
│   ├── identity_config.md      # Identity setup
│   ├── scouts.md               # Serverless shell design
│   └── FILE_INDEX.md           # This file
│
└── Configuration
    ├── requirements.txt        # Python dependencies
    └── .env.example            # Environment template
```

## Code Statistics (Updated)

- **Python files**: 2
- **Shell scripts**: 3
- **TypeScript files**: 4
- **Docker files**: 1
- **Documentation files**: 6
- **Configuration files**: 3
- **Total files**: 19

## Dependencies (Updated)

### Python Packages (from requirements.txt)
- fastapi
- uvicorn
- python-jose
- pydantic
- httpx
- python-dotenv

### Node.js Packages (from package.json)
- aws-cdk-lib
- constructs
- @aws-sdk/client-ecs
- @aws-sdk/client-dynamodb
- uuid

### System Requirements
- Docker
- bash
- zstd
- Python 3.11+
- Node.js 18+
- AWS CLI

## Source

All code extracted from ChatGPT conversation:
https://chatgpt.com/share/695a0e7f-dd14-8004-a308-d54851120225

The conversation covered designing a Zo-like personal cloud terminal with:
- Identity management (JWT-based)
- Session API
- Workspace isolation
- Container/microVM hosting
- Snapshot/restore functionality

Additional serverless shell implementation based on scouts.md requirements:
- AWS CDK infrastructure as code
- ECS Fargate containerized shells
- Lambda functions for orchestration
- DynamoDB session management
- Security-focused design
