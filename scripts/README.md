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