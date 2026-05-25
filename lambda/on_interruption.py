import os, datetime, boto3

ec2 = boto3.client("ec2", region_name=os.environ["REGION"])
ddb = boto3.client("dynamodb", region_name=os.environ["REGION"])
TABLE = os.environ["TABLE_NAME"]

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
    # EventBridge: EC2 Spot Instance Interruption Warning
    detail = event.get("detail", {})
    instance_id = detail.get("instance-id")
    if not instance_id:
        return {"skip": True}

    item = _find_run_by_instance(instance_id)
    if not item:
        return {"skip": "not our instance"}

    run_id = item["run_id"]["S"]
    
    # スポット中断通知時にuptimeを記録
    try:
        # インスタンスの情報を取得してLaunchTimeを確認
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        inst = desc["Reservations"][0]["Instances"][0]
        launch_time = inst.get("LaunchTime")
        
        if launch_time:
            # 現在時刻とLaunchTimeの差分を計算
            now = datetime.datetime.utcnow()
            uptime = int((now - launch_time.replace(tzinfo=None)).total_seconds())
            
            # DynamoDBを更新（中断フラグとuptimeを同時に設定）
            ddb.update_item(
                TableName=TABLE,
                Key={"run_id":{"S":run_id}},
                UpdateExpression="SET interrupted = :t, uptime_s = if_not_exists(uptime_s, :u)",
                ExpressionAttributeValues={
                    ":t":{"BOOL":True},
                    ":u":{"N":str(uptime)}
                }
            )
        else:
            # LaunchTimeが取得できない場合は中断フラグのみ設定
            ddb.update_item(
                TableName=TABLE,
                Key={"run_id":{"S":run_id}},
                UpdateExpression="SET interrupted = :t",
                ExpressionAttributeValues={":t":{"BOOL":True}}
            )
    except Exception as e:
        # エラーが発生した場合でも中断フラグは設定
        ddb.update_item(
            TableName=TABLE,
            Key={"run_id":{"S":run_id}},
            UpdateExpression="SET interrupted = :t",
            ExpressionAttributeValues={":t":{"BOOL":True}}
        )
        return {"error": str(e), "run_id": run_id}
    
    return {"ok": True, "run_id": run_id}
