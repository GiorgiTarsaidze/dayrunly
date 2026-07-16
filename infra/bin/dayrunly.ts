import * as cdk from 'aws-cdk-lib';
import { DayrunlyStack } from '../lib/dayrunly-stack';

const app = new cdk.App();
new DayrunlyStack(app, 'Dayrunly', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});
// Account convention: every resource of an app carries product=<app-name>
cdk.Tags.of(app).add('product', 'dayrunly');
