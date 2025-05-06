# Define variables
$PemPath = "C:\Users\royce\Downloads\MaintenanceInventory.pem"
$RemoteUser = "ubuntu"
$RemoteHost = "54.175.125.48"
$ProjectDir = "/home/ubuntu/IMS"

# Step 1: Connect and pull latest code from GitHub
ssh -i $PemPath "$RemoteUser@$RemoteHost" 'cd /home/ubuntu/ims && git pull origin main && sudo systemctl restart gunicorn'
