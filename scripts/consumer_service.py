#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-

"""
Consumer Service - Continuously listens for messages
"""

import json
import os
import socket
import uuid
import boto3
from kafka import KafkaConsumer
from kafka.sasl.oauth import AbstractTokenProvider
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

# Configuration from environment variables
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BROKERS = os.getenv(
    "MSK_BROKERS",
    "xx.xxx.xxx.xxx:9098,"
    "xx.xxx.xxx.xxx:9098,"  # Example brokers, replace with actual
).split(",")
TOPIC = os.getenv("MSK_TOPIC", "my-new-topic")
ROLE_ARN = os.getenv("ROLE_ARN")
CA_FILE = os.getenv("CA_FILE_PATH", "/app/certs/AmazonRootCA1.pem")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", f"consumer-group-{uuid.uuid4().hex[:6]}")

print(f"👂 Starting consumer service for topic '{TOPIC}'", flush=True)


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
        RoleSessionName=f"msk-consumer-{uuid.uuid4().hex[:6]}"
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


def safe_deserialize(b: bytes):
    """Try JSON, fallback to UTF-8 string, else raw bytes size"""
    if b is None:
        return None
    try:
        return json.loads(b.decode())
    except Exception:
        try:
            return b.decode()
        except Exception:
            return f"<{len(b)} bytes>"


def process_message(message):
    """Process a received message"""
    try:
        # Extract message data
        key = message.key
        value = message.value
        partition = message.partition
        offset = message.offset
        
        # Log basic info
        print(f"\n📥 [p{partition}@{offset}] key={key!r}", flush=True)
        
        # Process message content
        if isinstance(value, dict):
            msg_content = value.get('message', 'No message content')
            author = value.get('author', 'Unknown')
            priority = value.get('priority', 'N/A')
            timestamp = value.get('timestamp', 'N/A')
            msg_id = value.get('id', 'N/A')
            source = value.get('source', 'unknown')
            
            print(f"📄 Message ID: {msg_id}", flush=True)
            print(f"⏰ Timestamp: {timestamp}", flush=True)
            print(f"🎯 Priority: {priority}", flush=True)
            print(f"📡 Source: {source}", flush=True)
            print(f"✍️  Author: {author}", flush=True)
            print(f"💬 Content: {msg_content}", flush=True)
        else:
            print(f"📄 Raw value: {value}", flush=True)
            
    except Exception as e:
        print(f"❌ Error processing message: {e}", flush=True)
        print(f"📄 Raw message: {message}", flush=True)


def create_consumer():
    """Create Kafka consumer"""
    print(f"🔄 Initializing consumer with group '{CONSUMER_GROUP}'…", flush=True)
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BROKERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=IAMTokenProvider(),
        ssl_cafile=CA_FILE,
        group_id=CONSUMER_GROUP,
        client_id=f"consumer-{socket.gethostname()}",
        auto_offset_reset="earliest",  # Start from latest messages
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
        key_deserializer=safe_deserialize,
        value_deserializer=safe_deserialize,
        consumer_timeout_ms=60000,  # Timeout for polling
    )
    print("✅ Consumer ready", flush=True)
    return consumer


def main():
    """Main consumer loop"""
    maybe_assume_role()
    
    consumer = create_consumer()
    message_count = 0
    
    try:
        print("👂 Listening for messages... (Ctrl-C to stop)", flush=True)
        
        for message in consumer:
            message_count += 1
            print(f"\n🔔 Message {message_count} received:", flush=True)
            process_message(message)
            print("─" * 50, flush=True)
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping consumer service...", flush=True)
    except Exception as e:
        print(f"💥 Unexpected error: {e}", flush=True)
    finally:
        consumer.close()
        print("🏁 Consumer service stopped", flush=True)


if __name__ == "__main__":
    main()