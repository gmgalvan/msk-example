# MSK Helper 🚀

Python script for AWS MSK (Managed Streaming for Kafka) with IAM authentication. Supports sending priority messages and peeking/consuming from topics.

## Quick Start
```bash
# Set environment variables
export AWS_DEFAULT_REGION="us-east-1"
export MSK_BROKERS="broker1:9098,broker2:9098"
export MSK_TOPIC="your-topic"
export MSK_MSG_PRIORITY="5"
export ROLE_ARN="arn:aws:iam::account:role/your-role"  # optional

# Install dependencies
pip install kafka-python aws-msk-iam-sasl-signer boto3

# Download Amazon Root CA
wget https://www.amazontrust.com/repository/AmazonRootCA1.pem -O ~/.aws/msk-ca.pem

# Usage
python msk_helper.py send [priority]    # Send message with optional priority (1-10)
python msk_helper.py peek [limit]       # Peek messages with optional limit
```

## Environment Variables
- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `MSK_BROKERS`: Comma-separated broker endpoints
- `MSK_TOPIC`: Kafka topic name
- `MSK_MSG_PRIORITY`: Default message priority 1-10 (default: 5)
- `ROLE_ARN`: Optional IAM role to assume

## ECR Repository Manager

Pulumi TypeScript project for creating AWS ECR repositories with configurable settings.

### Quick Start

```bash
# Install dependencies
npm install

# Create and deploy a stack
pulumi stack init <stack-name>
pulumi up --stack <stack-name>
```

### Configuration

Create `Pulumi.<stack-name>.yaml` files to customize:
- Repository names
- Image scanning settings
- Encryption options
- Lifecycle policies

Each stack creates one ECR repository with the specified configuration.

## Docker Services Monitoring

Essential commands for monitoring and managing MSK services on EC2:

### Status Monitoring
```bash
# Check running containers
docker ps

# View real-time logs
docker logs -f msk-producer
docker logs -f msk-consumer

# Quick health check
docker logs --tail 5 msk-producer
docker logs --tail 5 msk-consumer

# Container resource usage
docker stats msk-producer msk-consumer
```

### Service Control
```bash
# Stop/start services
docker stop msk-producer msk-consumer
docker start msk-producer msk-consumer

# Restart services
docker restart msk-producer msk-consumer

# Fresh restart with latest images
docker stop msk-producer msk-consumer
docker rm msk-producer msk-consumer
docker pull <YOUR_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<PRODUCER_REPO>:latest
docker pull <YOUR_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<CONSUMER_REPO>:latest

# Start fresh containers
docker run -d --name msk-producer --env-file .env --restart unless-stopped <YOUR_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<PRODUCER_REPO>:latest
docker run -d --name msk-consumer --env-file .env --restart unless-stopped <YOUR_ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/<CONSUMER_REPO>:latest
```

### Quick Health Check Script
```bash
# Create monitoring script
cat > check_services.sh << 'EOF'
#!/bin/bash
echo "=== MSK Services Status ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | grep msk
echo ""
echo "=== Recent Activity ==="
echo "Producer:" && docker logs --tail 2 msk-producer | tail -1
echo "Consumer:" && docker logs --tail 2 msk-consumer | tail -1
EOF

chmod +x check_services.sh
./check_services.sh
```