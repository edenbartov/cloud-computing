KEY_NAME="yaron-eden-ex2-key"
KEY_PEM="$KEY_NAME.pem"
STACK_NAME="yaron-eden-stack"

echo "create key pair $KEY_PEM to connect to instances and save locally"
aws ec2 create-key-pair --key-name $KEY_NAME  --query "KeyMaterial" --output text > $KEY_PEM
# secure the key pair
chmod 600 $KEY_PEM

# figure out my ip
echo "getting my ip"
MY_IP=$(curl ipinfo.io/ip)
echo "My IP: $MY_IP"


# get subnets for the ELB and vpc id
echo "getting all subnets and vpc id's"
SUB_ID_1=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[0] | jq -r .SubnetId)
SUB_ID_2=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[1] | jq -r .SubnetId)
SUB_ID_3=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[2] | jq -r .SubnetId)
SUB_ID_4=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[3] | jq -r .SubnetId)
VPC_ID=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true | jq -r .Subnets[0] | jq -r .VpcId)
VPC_CIDR_BLOCK=$(aws ec2 describe-vpcs --filters Name=vpc-id,Values=$VPC_ID | jq -r .Vpcs[0].CidrBlock)
echo $SUB_ID_1
echo $SUB_ID_2
echo $SUB_ID_3
echo $SUB_ID_4
echo $VPC_ID
echo $VPC_CIDR_BLOCK

echo "createing stack yaron-eden stack"
STACK_RES=$(aws cloudformation create-stack --stack-name $STACK_NAME --template-body file://ec2CloudFormation.yml --capabilities CAPABILITY_NAMED_IAM \
	--parameters ParameterKey=InstanceType,ParameterValue=t2.micro \
	ParameterKey=KeyName,ParameterValue=$KEY_NAME \
	ParameterKey=SSHLocation,ParameterValue=$MY_IP/32 \
	ParameterKey=SubNetId1,ParameterValue=$SUB_ID_1 \
	ParameterKey=SubNetId2,ParameterValue=$SUB_ID_2 \
	ParameterKey=SubNetId3,ParameterValue=$SUB_ID_3 \
	ParameterKey=SubNetId4,ParameterValue=$SUB_ID_4 \
	ParameterKey=VPCId,ParameterValue=$VPC_ID \
	ParameterKey=VPCcidr,ParameterValue=$VPC_CIDR_BLOCK)

echo "waiting for stack $STACK_NAME to be created"
STACK_ID=$(echo $STACK_RES | jq -r '.StackId')
aws cloudformation wait stack-create-complete --stack-name $STACK_ID

REGION=us-east-1

# get the wanted stack 
STACK=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME | jq -r .Stacks[0])
# stack outputs
echo "printing stack outputs"
OUTPUTS=$(echo $STACK | jq -r .Outputs)
echo $OUTPUTS

echo "getting instances IP"
PUBLIC_IP_1=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance1IP'].OutputValue" --output text)
PUBLIC_IP_2=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance2IP'].OutputValue" --output text)
PUBLIC_IP_3=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance3IP'].OutputValue" --output text)
PUBLIC_IP_4=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='Instance4IP'].OutputValue" --output text)
ID4=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='InstanceId4'].OutputValue" --output text)
TGARN=$(aws cloudformation --region $REGION describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='TargetGroup'].OutputValue" --output text)



echo "waiting for instance to load"
sleep 30
#aws ec2 wait instance-status-ok --instance-ids $ID4
#target health check command
#aws elbv2 describe-target-health  --target-group-arn $TGARN


echo "waiting for instances to wake up properly"
DNS_ADD=$(aws elbv2 describe-load-balancers --names YaronandEdenELB | jq -r .LoadBalancers[0].DNSName)

#curl -X GET "@$DNS_ADD/health-check"
#sleep 1
#curl -X GET "@$PUBLIC_IP_1:8080/health-check"
#curl -X GET "@$PUBLIC_IP_2:8080/health-check"
#curl -X GET "@$PUBLIC_IP_3:8080/health-check"
#curl -X GET "@$PUBLIC_IP_4:8080/health-check"
#sleep 1

echo "access the ELB using this address:"
echo $DNS_ADD

echo "done"

