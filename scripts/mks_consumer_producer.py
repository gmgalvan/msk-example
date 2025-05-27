#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-

"""
  msk_helper.py – IAM-auth Producer/Consumer for Amazon MSK

  • Works on EC2/ECS (instance or task role)
  • Falls back to sts:AssumeRole if ROLE_ARN is set
  • Send supports a priority field
  • Peek streams messages; optional limit arg or infinite until Ctrl-C
  • Requires kafka-python >= 2.0 and aws-msk-iam-sasl-signer >= 1.0.2
"""

import json
import os
import sys
import socket
import time
import uuid
import boto3
from kafka import KafkaProducer, KafkaConsumer
from kafka.sasl.oauth import AbstractTokenProvider
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

# ─── USER SETTINGS ───────────────────────────────────────────────────────────
REGION           = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BROKERS = os.getenv(
    "MSK_BROKERS",
    "b-1.your-cluster.xxxxx.c23.kafka.us-east-1.amazonaws.com:9098,"
    "b-2.your-cluster.xxxxx.c23.kafka.us-east-1.amazonaws.com:9098"
).split(",")
TOPIC            = os.getenv("MSK_TOPIC", "xxxx-xxxx-xxxx-xxxx")  # e.g. "my-topic"
ROLE_ARN         = os.getenv("ROLE_ARN")            # optional – for sts assume
CA_FILE          = os.path.expanduser("~/.aws/msk-ca.pem")  # path to CA cert file
DEFAULT_PRIORITY = int(os.getenv("MSK_MSG_PRIORITY", "5"))  # 1 (highest) to 10 (lowest)
# ─────────────────────────────────────────────────────────────────────────────

print("⚙️  Starting msk_helper script…", flush=True)


def maybe_assume_role() -> None:
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
        RoleSessionName=f"msk-helper-{uuid.uuid4().hex[:6]}"
    )["Credentials"]
    os.environ.update({
        "AWS_ACCESS_KEY_ID":     out["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": out["SecretAccessKey"],
        "AWS_SESSION_TOKEN":     out["SessionToken"],
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


def new_producer() -> KafkaProducer:
    print(f"🎉 Initializing producer for topic '{TOPIC}'…", flush=True)
    producer = KafkaProducer(
        bootstrap_servers=BROKERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=IAMTokenProvider(),
        ssl_cafile=CA_FILE,
        client_id=socket.gethostname(),
        key_serializer=str.encode,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    print("✅ Producer ready", flush=True)
    return producer


def send_once(priority: int):
    print(f"🚀 Preparing to send to '{TOPIC}' with priority {priority}…", flush=True)
    p = new_producer()
    parts = sorted(p.partitions_for(TOPIC) or [])
    print(f"📊 Partitions → {parts}", flush=True)
    payload = {"msg": "hello my name is Memo", "ts": int(time.time()), "priority": priority}
    print(f"📤 Sending: {payload}", flush=True)
    md = p.send(TOPIC, key="iam", value=payload).get(timeout=15)
    print(f"✅ Sent to partition {md.partition} offset {md.offset}", flush=True)
    p.close()


def peek_once(limit: int = None):
    print("🔄 Starting peek…", flush=True)
    c = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BROKERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=IAMTokenProvider(),
        ssl_cafile=CA_FILE,
        group_id=f"peek-any-{uuid.uuid4().hex[:6]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        key_deserializer=safe_deserialize,
        value_deserializer=safe_deserialize,
    )
    print("…streaming; Ctrl-C to stop", flush=True)
    count = 0
    for msg in c:
        print(f"📥 [p{msg.partition}@{msg.offset}] key={msg.key!r} value={msg.value}")
        count += 1
        if limit is not None and count >= limit:
            break
    c.close()
    print("🏁 Peek complete", flush=True)


def usage():
    print("❗ Usage: {} send [priority] | peek [limit]".format(sys.argv[0]), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"send", "peek"}:
        usage()
    maybe_assume_role()
    if sys.argv[1] == "send":
        pr = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PRIORITY
        send_once(pr)
    else:
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
        peek_once(lim)
