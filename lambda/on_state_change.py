import os, datetime
import boto3

ec2 = boto3.client("ec2", region_name=os.environ["REGION"])
ddb = boto3.client("dynamodb", region_name=os.environ["REGION"])

TABLE = os.environ["TABLE_NAME"]

def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)

def _find_run_by_instance(instance_id: str):
    resp = ddb.query(
        TableName=TABLE,
        IndexName="by_instance_id",
        KeyConditionExpression="instance_id = :iid",
        ExpressionAttributeValues={":iid": {"S": instance_id}},
        Limit=1
    )
    items = resp.get("Items", [])
    return items[0] if items else None

def handler(event, context):
    # EventBridge EC2 state-change
    detail = event.get("detail", {})
    instance_id = detail.get("instance-id")
    state = detail.get("state")

    if not instance_id or state not in ("running", "terminated"):
        return {"skip": True}

    item = _find_run_by_instance(instance_id)
    if not item:
        return {"skip": "not our instance"}

    run_id = item["run_id"]["S"]

    if state == "running":
        running_at = _now_utc()
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        inst = desc["Reservations"][0]["Instances"][0]
        az = inst["Placement"]["AvailabilityZone"]
        launch_time = inst["LaunchTime"]  # timezone-aware datetime
        startup_s = int((running_at - launch_time).total_seconds())
        ddb.update_item(
            TableName=TABLE,
            Key={"run_id": {"S": run_id}},
            UpdateExpression="SET success = :t, az = :az, launch_time = :lt, running_at = :ra, startup_s = :ss",
            ExpressionAttributeValues={
                ":t":  {"BOOL": True},
                ":az": {"S": az},
                ":lt": {"S": launch_time.strftime("%Y-%m-%dT%H:%M:%SZ")},
                ":ra": {"S": running_at.strftime("%Y-%m-%dT%H:%M:%SZ")},
                ":ss": {"N": str(startup_s)},
            }
        )

    elif state == "terminated":
        # uptimeが未記録ならLaunchTime→今で補完（インスタンス側の更新が間に合わなかったケース対策）
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        inst = desc["Reservations"][0]["Instances"][0]
        launch_time = inst.get("LaunchTime")
        if launch_time:
            uptime = int((_now_utc() - launch_time).total_seconds())
            try:
                ddb.update_item(
                    TableName=TABLE,
                    Key={"run_id": {"S": run_id}},
                    UpdateExpression="SET uptime_s = if_not_exists(uptime_s, :u)",
                    ExpressionAttributeValues={":u": {"N": str(uptime)}}
                )
            except Exception:
                pass

    return {"ok": True, "state": state, "run_id": run_id}
