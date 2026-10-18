# spotinstance-IaC

## 特定のインスタンスをターゲットにした FIS テンプレ

```bash
aws fis create-experiment-template \
  --cli-input-json '{
    "description": "Terminate specific Spot instance",
    "targets": {
      "myTarget": {
        "resourceType": "aws:ec2:instance",
        "resourceArns": [
          "arn:aws:ec2:ap-northeast-1:123456789012:instance/i-0abc123def456gh78"
        ],
        "selectionMode": "ALL"
      }
    },
    "actions": {
      "terminateInstances": {
        "actionId": "aws:ec2:terminate-instances",
        "parameters": {},
        "targets": {
          "Instances": "myTarget"
        }
      }
    },
    "roleArn": "arn:aws:iam::123456789012:role/fis-experiment-role",
    "stopConditions": [
      { "source": "none" }
    ],
    "tags": {
      "Name": "terminate-specific-spot"
    }
  }'

```

```bash
上のコマンドの返り値
aws fis start-experiment --experiment-template-id <experimentTemplateId>
```
# nagisa-researrch
