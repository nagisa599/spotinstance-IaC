import os, json, base64, random, uuid, time, datetime
from zoneinfo import ZoneInfo
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# InsufficientInstanceCapacity は別AZで試すべきエラーなので SDK 側の自動リトライは無効化
_no_retry = Config(retries={"max_attempts": 1, "mode": "standard"})
ec2 = boto3.client("ec2", region_name=os.environ["REGION"], config=_no_retry)
ddb = boto3.client("dynamodb", region_name=os.environ["REGION"])

TABLE = os.environ["TABLE_NAME"]
AMI_ID = os.environ["AMI_ID"]
INSTANCE_PROFILE = os.environ["INSTANCE_PROFILE_NAME"]
SECURITY_GROUP_ID = os.environ["SECURITY_GROUP_ID"]
SUBNET_IDS = json.loads(os.environ["SUBNET_IDS_JSON"])
INSTANCE_TYPES = json.loads(os.environ["INSTANCE_TYPES_JSON"])
PROJECT_TAG = os.environ.get("PROJECT_TAG", "spot-exp")

# これらのエラーはAZ単位の問題なので別AZでリトライする
RETRYABLE_ERROR_CODES = ("Unsupported", "InsufficientInstanceCapacity", "InsufficientCapacity")

USER_DATA_TEMPLATE = r"""#!/bin/bash
set -euo pipefail

RUN_ID="{{RUN_ID}}"
TABLE="{{TABLE}}"
REGION="{{REGION}}"

# 時刻（UTC）
START_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# 中断警告監視（インスタンスメタデータ）
( while true; do
  if curl -fs http://169.254.169.254/latest/meta-data/spot/instance-action >/dev/null; then
    /usr/bin/aws dynamodb update-item \
      --region $REGION \
      --table-name "$TABLE" \
      --key "{\"run_id\":{\"S\":\"$RUN_ID\"}}" \
      --update-expression "SET interrupted = :t" \
      --expression-attribute-values "{\":t\":{\"BOOL\":true}}"
    break
  fi
  sleep 5
done ) &

# 最大3600秒待機 (60分の場合　3600秒)
TIMEOUT=3600
sleep "${TIMEOUT}"

# 正常終了としてuptimeを更新（terminatedイベント側でも補完するが二重でもOK）
END_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
UPTIME=$(( $(date -d "$END_TS" +%s) - $(date -d "$START_TS" +%s) ))

/usr/bin/aws dynamodb update-item \
  --region $REGION \
  --table-name "$TABLE" \
  --key "{\"run_id\":{\"S\":\"$RUN_ID\"}}" \
  --update-expression "SET uptime_s = :u" \
  --expression-attribute-values "{\":u\":{\"N\":\"$UPTIME\"}}"

# インスタンス側のシャットダウン -> EC2側はterminateにする（起動時指定）
/sbin/shutdown -h now
"""

def _tokyo_day_period(now_utc: datetime.datetime) -> str:
    jst = now_utc.astimezone(ZoneInfo("Asia/Tokyo"))
    hour = jst.hour
    return "day" if 8 <= hour < 20 else "night"

def _latest_spot_price(instance_type: str, az: str) -> float | None:
    resp = ec2.describe_spot_price_history(
        InstanceTypes=[instance_type],
        ProductDescriptions=["Linux/UNIX"],
        AvailabilityZone=az,
        MaxResults=1,
        StartTime=datetime.datetime.now(datetime.timezone.utc),
    )
    items = resp.get("SpotPriceHistory", [])
    if not items:
        return None
    return float(items[0]["SpotPrice"])

def handler(event, context):
    region = os.environ["REGION"]

    for instance_type in INSTANCE_TYPES:
        run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        request_at = datetime.datetime.now(datetime.timezone.utc)
        day_period = _tokyo_day_period(request_at)

        # サブネットをシャッフルして順に試す
        subnets_shuffled = random.sample(SUBNET_IDS, len(SUBNET_IDS))
        launched = False
        last_error = None
        retry_count = 0

        for subnet_id in subnets_shuffled:
            subnet = ec2.describe_subnets(SubnetIds=[subnet_id])["Subnets"][0]
            az = subnet["AvailabilityZone"]
            spot_price = _latest_spot_price(instance_type, az)

            user_data = USER_DATA_TEMPLATE \
                .replace("{{RUN_ID}}", run_id) \
                .replace("{{TABLE}}", TABLE) \
                .replace("{{REGION}}", region)
            user_data_b64 = base64.b64encode(user_data.encode("utf-8")).decode("utf-8")

            try:
                resp = ec2.run_instances(
                    ImageId=AMI_ID,
                    InstanceType=instance_type,
                    MinCount=1,
                    MaxCount=1,
                    InstanceMarketOptions={"MarketType": "spot"},
                    IamInstanceProfile={"Name": INSTANCE_PROFILE},
                    NetworkInterfaces=[{
                        "AssociatePublicIpAddress": True,
                        "DeviceIndex": 0,
                        "SubnetId": subnet_id,
                        "Groups": [SECURITY_GROUP_ID],
                    }],
                    UserData=user_data_b64,
                    InstanceInitiatedShutdownBehavior="terminate",
                    TagSpecifications=[{
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name",       "Value": f"SpotTest-{instance_type}-{run_id}"},
                            {"Key": "Project",    "Value": PROJECT_TAG},
                            {"Key": "Experiment", "Value": "SpotStudy2025"},
                            {"Key": "RunId",      "Value": run_id},
                            {"Key": "DayPeriod",  "Value": day_period},
                            {"Key": "Type",       "Value": instance_type},
                            {"Key": "Interrupt",  "Value": "interruptMe"},
                        ],
                    }],
                )
                instance_id = resp["Instances"][0]["InstanceId"]
                ddb.put_item(
                    TableName=TABLE,
                    Item={
                        "run_id":        {"S": run_id},
                        "instance_id":   {"S": instance_id},
                        "instance_type": {"S": instance_type},
                        "subnet_id":     {"S": subnet_id},
                        "az":            {"S": az},
                        "timestamp":     {"S": request_at.strftime("%Y-%m-%dT%H:%M:%SZ")},
                        "day_period":    {"S": day_period},
                        "spot_price":    {"N": str(spot_price) if spot_price is not None else "0"},
                        "region":        {"S": region},
                        "retry_count":   {"N": str(retry_count)},
                        "success":       {"BOOL": False},
                        "interrupted":   {"BOOL": False},
                        "launch_failed": {"BOOL": False},
                    },
                )
                launched = True
                break

            except ClientError as e:
                last_error = e
                if e.response["Error"]["Code"] in RETRYABLE_ERROR_CODES:
                    retry_count += 1
                    continue  # 別AZで再試行
                else:
                    break  # クォータ超過など非リトライエラーはすぐ記録

        if not launched:
            ddb.put_item(
                TableName=TABLE,
                Item={
                    "run_id":        {"S": run_id},
                    "instance_type": {"S": instance_type},
                    "az":            {"S": az},
                    "timestamp":     {"S": request_at.strftime("%Y-%m-%dT%H:%M:%SZ")},
                    "day_period":    {"S": day_period},
                    "spot_price":    {"N": str(spot_price) if spot_price is not None else "0"},
                    "region":        {"S": region},
                    "retry_count":   {"N": str(retry_count)},
                    "success":       {"BOOL": False},
                    "interrupted":   {"BOOL": False},
                    "launch_failed": {"BOOL": True},
                    "error_message": {"S": str(last_error)},
                },
            )

    return {"ok": True, "launched": INSTANCE_TYPES}
