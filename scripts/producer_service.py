#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-

"""
Producer Service - Sends messages every minute
Uses either random quotes from an API or local file messages
"""

import json
import os
import time
import random
import requests
import socket
import uuid
from kafka import KafkaProducer
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from kafka.sasl.oauth import AbstractTokenProvider
import boto3

# Configuration from environment variables
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BROKERS = os.getenv(
    "MSK_BROKERS",
    "b-1.devmskcluster.8kq2ef.c23.kafka.us-east-1.amazonaws.com:9098,"
    "b-2.devmskcluster.8kq2ef.c23.kafka.us-east-1.amazonaws.com:9098"
).split(",")
TOPIC = os.getenv("MSK_TOPIC", "my-new-topic")
ROLE_ARN = os.getenv("ROLE_ARN")
CA_FILE = os.getenv("CA_FILE_PATH", "/app/certs/AmazonRootCA1.pem")
MESSAGE_INTERVAL = int(os.getenv("MESSAGE_INTERVAL", "60"))  # seconds
USE_API = os.getenv("USE_API", "true").lower() == "true"
DEFAULT_PRIORITY = int(os.getenv("MSK_MSG_PRIORITY", "5"))

print(f"🚀 Starting producer service with {MESSAGE_INTERVAL}s interval", flush=True)


def maybe_assume_role():
    if not ROLE_ARN:
        return
    sess = boto3.Session(region_name=REGION)
    creds = sess.get_credentials()
    if creds and creds.token:
        print("🔑 Using existing temporary credentials…", flush=True)
        return
    sts = sess.client("sts")
    print(f"🔐 ⤷ Assuming role {ROLE_ARN.split('/')[-1]}…", flush=True)
    out = sts.assume_role(
        RoleArn=ROLE_ARN,
        RoleSessionName=f"msk-producer-{uuid.uuid4().hex[:6]}"
    )["Credentials"]
    os.environ.update({
        "AWS_ACCESS_KEY_ID": out["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": out["SecretAccessKey"],
        "AWS_SESSION_TOKEN": out["SessionToken"],
    })
    print(f"✅ Temporary creds acquired, expire at {out['Expiration']}", flush=True)


class IAMTokenProvider(AbstractTokenProvider):
    def __init__(self):
        print("⏳ Generating IAM auth token…", flush=True)
        self._token, _ = MSKAuthTokenProvider.generate_auth_token(region=REGION)
        print("🔑 Token ready", flush=True)
    
    def token(self) -> str:
        return self._token


def get_random_quote_api():
    """Get random quote from free API"""
    try:
        response = requests.get("https://api.quotable.io/random", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "message": data.get("content", "No content"),
                "author": data.get("author", "Unknown"),
                "source": "quotable_api"
            }
    except Exception as e:
        print(f"❌ API request failed: {e}", flush=True)
    
    # Fallback quote
    return {
        "message": "The best way to predict the future is to create it.",
        "author": "Peter Drucker",
        "source": "fallback"
    }


def get_random_quote_file():
    """Get random quote from local file"""
    try:
        with open("sample_messages.json", "r") as f:
            messages = json.load(f)
        return random.choice(messages)
    except Exception as e:
        print(f"❌ File read failed: {e}", flush=True)
        return {
            "message": "Local file message not available",
            "author": "System",
            "source": "fallback"
        }


def create_producer():
    """Create Kafka producer"""
    print(f"🎉 Initializing producer for topic '{TOPIC}'…", flush=True)
    producer = KafkaProducer(
        bootstrap_servers=BROKERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=IAMTokenProvider(),
        ssl_cafile=CA_FILE,
        client_id=f"producer-{socket.gethostname()}",
        key_serializer=str.encode,
        value_serializer=lambda v: json.dumps(v).encode(),
        retries=3,
        retry_backoff_ms=1000,
    )
    print("✅ Producer ready", flush=True)
    return producer


def send_message(producer, message_data):
    """Send a single message"""
    try:
        # Add metadata
        payload = {
            **message_data,
            "timestamp": int(time.time()),
            "priority": random.randint(1, 10),
            "service": "producer",
            "id": str(uuid.uuid4())
        }
        
        print(f"📤 Sending: {payload['message'][:50]}...", flush=True)
        
        # Send message
        future = producer.send(TOPIC, key="producer", value=payload)
        record_metadata = future.get(timeout=10)
        
        print(f"✅ Sent to partition {record_metadata.partition} offset {record_metadata.offset}", flush=True)
        return True
        
    except Exception as e:
        print(f"❌ Failed to send message: {e}", flush=True)
        return False


def main():
    """Main producer loop"""
    maybe_assume_role()
    
    producer = create_producer()
    message_count = 0
    
    try:
        while True:
            message_count += 1
            print(f"\n🔄 Iteration {message_count} - Getting message...", flush=True)
            
            # Get message content
            if USE_API:
                message_data = get_random_quote_api()
                print(f"📡 Using API message", flush=True)
            else:
                message_data = get_random_quote_file()
                print(f"📁 Using file message", flush=True)
            
            # Send message
            success = send_message(producer, message_data)
            
            if success:
                print(f"💤 Waiting {MESSAGE_INTERVAL}s until next message...", flush=True)
            else:
                print(f"⚠️  Message failed, retrying in {MESSAGE_INTERVAL}s...", flush=True)
            
            time.sleep(MESSAGE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping producer service...", flush=True)
    except Exception as e:
        print(f"💥 Unexpected error: {e}", flush=True)
    finally:
        producer.close()
        print("🏁 Producer service stopped", flush=True)


if __name__ == "__main__":
    main()