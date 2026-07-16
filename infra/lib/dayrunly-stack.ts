import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as ssm from 'aws-cdk-lib/aws-ssm';

const RUNDOWNLY_TABLE = 'rundownly-main';
const TIMEZONE = 'Asia/Tbilisi';

export class DayrunlyStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const audit = new dynamodb.Table(this, 'AuditTable', {
      tableName: 'dayrunly-audit',
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const fn = new lambda.Function(this, 'Agent', {
      functionName: 'dayrunly-agent',
      runtime: lambda.Runtime.PYTHON_3_13,
      code: lambda.Code.fromAsset('../agent', { exclude: ['__pycache__'] }),
      handler: 'handler.lambda_handler',
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      environment: {
        AUDIT_TABLE: audit.tableName,
        RUNDOWNLY_TABLE,
        DRY_RUN: this.node.tryGetContext('dryRun') ? 'true' : 'false',
      },
      logGroup: new logs.LogGroup(this, 'AgentLogs', {
        logGroupName: '/aws/lambda/dayrunly-agent',
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    audit.grantReadWriteData(fn);

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ReadDayrunlyParams',
      actions: ['ssm:GetParameter', 'ssm:GetParameters'],
      resources: [this.formatArn({ service: 'ssm', resource: 'parameter', resourceName: 'dayrunly/*' })],
    }));

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ReadRundownlyDigests',
      actions: ['dynamodb:GetItem', 'dynamodb:Query'],
      resources: [this.formatArn({ service: 'dynamodb', resource: 'table', resourceName: RUNDOWNLY_TABLE })],
    }));

    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'InvokeNova',
      actions: ['bedrock:InvokeModel'],
      resources: [`arn:${this.partition}:bedrock:${this.region}::foundation-model/amazon.nova-*`],
    }));

    // Recipient/sender identity is resolved from SSM at deploy time — the
    // address itself never appears in this public repo.
    const email = ssm.StringParameter.valueForStringParameter(this, '/dayrunly/config/email');
    fn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'SendBriefs',
      actions: ['ses:SendEmail'],
      resources: [this.formatArn({ service: 'ses', resource: 'identity', resourceName: email })],
    }));

    const schedulerRole = new iam.Role(this, 'SchedulerRole', {
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
    });
    fn.grantInvoke(schedulerRole);

    const enabled = this.node.tryGetContext('schedulesEnabled') === true
      || this.node.tryGetContext('schedulesEnabled') === 'true';

    const runs: Array<[string, string, string]> = [
      ['MorningRun', 'cron(0 9 * * ? *)', 'morning'],
      ['EveningRun', 'cron(30 21 * * ? *)', 'evening'],
    ];
    for (const [name, cron, runType] of runs) {
      new scheduler.CfnSchedule(this, name, {
        name: `dayrunly-${runType}`,
        scheduleExpression: cron,
        scheduleExpressionTimezone: TIMEZONE,
        state: enabled ? 'ENABLED' : 'DISABLED',
        flexibleTimeWindow: { mode: 'OFF' },
        target: {
          arn: fn.functionArn,
          roleArn: schedulerRole.roleArn,
          input: JSON.stringify({ run_type: runType }),
          retryPolicy: { maximumRetryAttempts: 1, maximumEventAgeInSeconds: 900 },
        },
      });
    }

    new cdk.CfnOutput(this, 'FunctionName', { value: fn.functionName });
  }
}
