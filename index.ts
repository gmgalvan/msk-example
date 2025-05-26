import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";
import * as random from "@pulumi/random";

// --------------------------------------------------------------------------------
// 1. CONFIGURATION
//    Read AWS provider and MSK-specific settings from Pulumi config
// --------------------------------------------------------------------------------
const awsCfg = new pulumi.Config("aws");
const awsRegion = (awsCfg.get("region") ?? "us-east-1") as aws.Region;
const awsProfile = awsCfg.get("profile");

const mskCfg = new pulumi.Config("msk");
const clusterName        = mskCfg.require("clusterName");
const kafkaVersion       = mskCfg.require("kafkaVersion");
const brokerNodeType     = mskCfg.require("brokerNodeType");
const brokerCount        = mskCfg.requireNumber("brokerCount");
const subnetIds          = mskCfg.requireObject<string[]>("subnetIds");
const brokerIngressCidrBlocks = mskCfg.requireObject<string[]>("brokerIngressCidrBlocks");
const ec2InstanceType    = mskCfg.require("ec2InstanceType");
const ec2AmiId           = mskCfg.require("ec2AmiId");
const ec2KeyName         = mskCfg.require("ec2KeyName");
const tags               = mskCfg.getObject<Record<string, string>>("tags") || {};
const enableCWLogs       = mskCfg.getBoolean("enableCloudWatchLogs") ?? true;
const logRetentionDays   = mskCfg.getNumber("logRetentionDays") ?? 7;

// --------------------------------------------------------------------------------
// 2. AWS PROVIDER
//    Create a named AWS provider instance for this stack
// --------------------------------------------------------------------------------
const providerName = awsProfile ?? "default";
const awsProvider = new aws.Provider(providerName, {
  region:  awsRegion,
  profile: awsProfile,
});

// Retrieve AWS Account ID for IAM policies
const callerIdentity = aws.getCallerIdentity({}, { provider: awsProvider });
const accountId      = callerIdentity.then(id => id.accountId);

// --------------------------------------------------------------------------------
// 3. NETWORK PREREQUISITES
//    Determine VPC and Subnet IDs, and prepare security rule helpers
// --------------------------------------------------------------------------------
const ec2SubnetId = pulumi.output(subnetIds)[0];
const vpcId = ec2SubnetId.apply(id =>
  aws.ec2.getSubnet({ id }, { provider: awsProvider }).then(s => s.vpcId)
);

function buildTcpRules(ports: number[], cidrs: string[]) {
  return ports.flatMap(port => cidrs.map(cidr => ({
    protocol: "tcp",
    fromPort: port,
    toPort: port,
    cidrBlocks: [cidr],
  })));
}

const kafkaPorts = [9092, 9094, 9096, 9098];

// --------------------------------------------------------------------------------
// 4. SECURITY GROUPS
//    - EC2 client: SSH ingress and Kafka egress
//    - MSK brokers: Kafka ingress
// --------------------------------------------------------------------------------
const ec2Sg = new aws.ec2.SecurityGroup("ec2-client-sg", {
  vpcId:      vpcId,
  description:"Allow SSH and Kafka egress",
  ingress: [
    { protocol: "tcp", fromPort: 22, toPort: 22, cidrBlocks: ["0.0.0.0/0"] },
  ],
  egress: [
    ...buildTcpRules(kafkaPorts, brokerIngressCidrBlocks),
    { protocol: "-1", fromPort: 0, toPort: 0, cidrBlocks: ["0.0.0.0/0"] },
  ],
}, { provider: awsProvider });

const mskSg = new aws.ec2.SecurityGroup("msk-broker-sg", {
  vpcId:      vpcId,
  description:"Allow Kafka ports ingress: plaintext, TLS, SCRAM, IAM",
  ingress:   buildTcpRules(kafkaPorts, brokerIngressCidrBlocks),
  egress: [ { protocol: "-1", fromPort: 0, toPort: 0, cidrBlocks: ["0.0.0.0/0"] } ],
}, { provider: awsProvider });

// --------------------------------------------------------------------------------
// 5. CLOUDWATCH LOGGING (Optional)
//    Create log group and resource policy if enabled
// --------------------------------------------------------------------------------
let mskLogGroup: aws.cloudwatch.LogGroup | undefined;
if (enableCWLogs) {
  mskLogGroup = new aws.cloudwatch.LogGroup("msk-broker-logs", {
    retentionInDays: logRetentionDays,
    tags:            { Name: `${clusterName}-broker-logs` },
  }, { provider: awsProvider });

  new aws.cloudwatch.LogResourcePolicy("msk-log-policy", {
    policyName: `${clusterName}-msk-log-policy`,
    policyDocument: pulumi.interpolate`{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": { "Service": "logs.amazonaws.com" },
        "Action": ["logs:PutLogEvents","logs:CreateLogStream"],
        "Resource": "${mskLogGroup.arn}:*"
      }]
    }`,
  }, { provider: awsProvider });
}

// --------------------------------------------------------------------------------
// 6. CUSTOM MSK CONFIGURATION
//    Define server properties and attach to cluster
// --------------------------------------------------------------------------------
const customConfig = `
auto.create.topics.enable=true
default.replication.factor=${brokerCount > 1 ? 2 : 1}
min.insync.replicas=1
num.partitions=6
log.retention.hours=168
delete.topic.enable=true
`;
const mskConfiguration = new aws.msk.Configuration("msk-custom-config", {
  name: `${clusterName}-config`,
  kafkaVersions: [kafkaVersion],
  serverProperties: customConfig,
}, { provider: awsProvider });

// --------------------------------------------------------------------------------
// 7. MSK CLUSTER
//    Launch managed Kafka cluster with IAM/SCRAM auth, encryption, logging, monitoring
// --------------------------------------------------------------------------------
const mskCluster = new aws.msk.Cluster(clusterName, {
  clusterName,
  kafkaVersion,
  numberOfBrokerNodes: brokerCount,
  brokerNodeGroupInfo: {
    instanceType:   brokerNodeType,
    clientSubnets:  subnetIds,
    securityGroups: [mskSg.id],
  },
  clientAuthentication: { sasl: { iam: true, scram: true } },
  encryptionInfo:      { encryptionInTransit: { clientBroker: "TLS", inCluster: true } },
  configurationInfo:   {
    arn: mskConfiguration.arn,
    revision: mskConfiguration.latestRevision,
  },
  loggingInfo: enableCWLogs && mskLogGroup
    ? { brokerLogs: { cloudwatchLogs: { enabled: true, logGroup: mskLogGroup.name } } }
    : undefined,
  openMonitoring:      {
    prometheus: {
      jmxExporter:  { enabledInBroker: true },
      nodeExporter: { enabledInBroker: true },
    },
  },
  tags,
}, { provider: awsProvider });

// --------------------------------------------------------------------------------
// 8. EC2 TEST CLIENT
//    Spin up an EC2 instance to test connectivity to the Kafka cluster
// --------------------------------------------------------------------------------
const ec2Client = new aws.ec2.Instance("msk-client", {
  instanceType:       ec2InstanceType,
  ami:                ec2AmiId,
  keyName:            ec2KeyName,
  subnetId:           ec2SubnetId,
  vpcSecurityGroupIds:[ec2Sg.id],
  tags:               { ...tags, Name: `${clusterName}-client` },
}, { provider: awsProvider });

// --------------------------------------------------------------------------------
// 9. SCRAM CREDENTIALS & SECRETS
//    Generate password, create KMS key and Secret, associate with MSK
// --------------------------------------------------------------------------------
const scramPwd = new random.RandomPassword("scramPwd", {
  length:         16,
  overrideSpecial:"_%@",
});

const scramKey = new aws.kms.Key("mskScramKey", {
  description: "KMS key for MSK SCRAM secrets",
}, { provider: awsProvider });

new aws.kms.Alias("mskScramKeyAlias", {
  name:        pulumi.interpolate`alias/${clusterName}-msk-scram-key`,
  targetKeyId: scramKey.keyId,
}, { provider: awsProvider });

const scramSecret = new aws.secretsmanager.Secret("mskScramUserSecret", {
  name:        pulumi.interpolate`AmazonMSK_${clusterName}_user`,
  description: "SCRAM credentials for MSK",
  kmsKeyId:    scramKey.id,
}, { provider: awsProvider });

const scramSecretVersion = new aws.secretsmanager.SecretVersion("mskScramUserSecretVersion", {
  secretId:     scramSecret.id,
  secretString: pulumi.interpolate`{"username":"msk-user","password":"${scramPwd.result}"}`,
}, { provider: awsProvider });

new aws.msk.SingleScramSecretAssociation("mskScramAssoc", {
  clusterArn: mskCluster.arn,
  secretArn:  scramSecret.arn,
}, {
  dependsOn: [scramSecretVersion],
  provider: awsProvider,
});

// --------------------------------------------------------------------------------
// 10. CLUSTER IAM POLICY
//     Grant root account permissions to manage the cluster
// --------------------------------------------------------------------------------
new aws.msk.ClusterPolicy("mskClusterPolicy", {
  clusterArn: mskCluster.arn,
  policy: pulumi.interpolate`{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::${accountId}:root" },
      "Action": [
        "kafka:GetBootstrapBrokers",
        "kafka:DescribeCluster",
        "kafka:CreateVpcConnection",
        "kafka:DescribeClusterV2"
      ],
      "Resource": "${mskCluster.arn}"
    }]
  }`,
}, { provider: awsProvider });

// --------------------------------------------------------------------------------
// 11. EXPORTS
// --------------------------------------------------------------------------------
export const bootstrapBrokers           = mskCluster.bootstrapBrokers;
export const bootstrapBrokersTls        = mskCluster.bootstrapBrokersTls;
export const bootstrapBrokersSaslScram  = mskCluster.bootstrapBrokersSaslScram;
export const bootstrapBrokersSaslIam    = mskCluster.bootstrapBrokersSaslIam;
export const clusterArn                 = mskCluster.arn;
export const zookeeperConnectString     = mskCluster.zookeeperConnectString;
export const ec2ClientPublicIp          = ec2Client.publicIp;
