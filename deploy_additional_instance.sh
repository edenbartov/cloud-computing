KEY_NAME="yaron-eden-ex2-key"
STACK_NAME="yaron-eden-new-instance-stack"
REGION=us-east-1
# get the ip of this machine
echo "getting my ip"
MY_IP=$(curl ipinfo.io/ip)

#get all the network parameters
echo "get all the network parameters"
SEC_GROUP=$(aws ec2 describe-security-groups --group-names YaronEdenEC2SecurityGroup | jq -r .SecurityGroups[0].GroupId)


echo "creating new stack for and deploying new instance"
STACK_RES=$(aws cloudformation create-stack --stack-name $STACK_NAME --template-body file://deploy_additional_instance_template.yml --capabilities CAPABILITY_IAM \
	--parameters ParameterKey=InstanceType,ParameterValue=t2.micro \
    ParameterKey=KeyName,ParameterValue=$KEY_NAME \
	ParameterKey=SecGroupId,ParameterValue=$SEC_GROUP)

echo "stack is being created, this might take some time"
STACK_ID=$(echo $STACK_RES | jq -r '.StackId')
aws cloudformation wait stack-create-complete --stack-name $STACK_ID
#get stack
STACK=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME | jq -r .Stacks[0])

# stack outputs
echo "getting the stack parameters"
OUTPUTS=$(echo $STACK | jq -r .Outputs)
InstanceIP=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceIP'].OutputValue" --output text)
InstanceId=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
TGARN=$(aws cloudformation --region $REGION describe-stacks --stack-name yaron-eden-stack --query "Stacks[0].Outputs[?OutputKey=='TargetGroup'].OutputValue" --output text)

echo "new instance IP: $InstanceIP"

# register the new instance to target group
echo "registering the new instance to target group"
aws elbv2 register-targets --target-group-arn $TGARN --targets Id=$InstanceId,Port=8080

echo "wait until the instance is ok"
aws ec2 wait instance-status-ok --instance-ids $InstanceId

echo "checking that the ELB is healthy"
aws elbv2 describe-target-health  --target-group-arn $TGARN
echo "done deploy"
