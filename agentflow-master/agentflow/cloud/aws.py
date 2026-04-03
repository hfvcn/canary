"""AWS infrastructure auto-discovery and credential forwarding."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def discover_networking(region: str) -> dict[str, Any]:
    """Find default VPC, public subnets, and create/reuse a security group.

    Returns ``{"subnets": [...], "security_groups": [...]}`` ready to
    plug into an EC2Target or ECSTarget.
    """
    import boto3

    ec2 = boto3.client("ec2", region_name=region)

    # Find default VPC
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError(f"No default VPC in {region}. Specify subnets/security_groups explicitly.")
    vpc_id = vpcs[0]["VpcId"]

    # Find public subnets (with auto-assign public IP or mapped to an IGW route)
    all_subnets = ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}],
    )["Subnets"]
    subnets = [s["SubnetId"] for s in all_subnets if s.get("MapPublicIpOnLaunch", False)]
    if not subnets:
        # Fallback: just use all subnets in the default VPC
        subnets = [s["SubnetId"] for s in all_subnets]
    if not subnets:
        raise RuntimeError(f"No subnets found in default VPC {vpc_id}.")

    # Create or reuse agentflow security group
    sg_name = "agentflow"
    existing = ec2.describe_security_groups(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "group-name", "Values": [sg_name]},
        ],
    )["SecurityGroups"]
    if existing:
        sg_id = existing[0]["GroupId"]
    else:
        sg_id = ec2.create_security_group(
            GroupName=sg_name,
            Description="AgentFlow managed security group",
            VpcId=vpc_id,
        )["GroupId"]
        # Allow SSH inbound (for EC2 runner)
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            ],
        )
        # Allow all outbound (default, but be explicit)
        # Already allowed by default SG rules

    return {"subnets": subnets[:3], "security_groups": [sg_id]}


def discover_ubuntu_ami(region: str) -> str:
    """Find the latest Ubuntu 24.04 amd64 AMI in a region."""
    import boto3

    ec2 = boto3.client("ec2", region_name=region)
    images = ec2.describe_images(
        Owners=["099720109477"],  # Canonical
        Filters=[
            {"Name": "name", "Values": ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]},
            {"Name": "state", "Values": ["available"]},
        ],
    )["Images"]
    if not images:
        raise RuntimeError(f"No Ubuntu 24.04 AMI found in {region}")
    images.sort(key=lambda i: i["CreationDate"], reverse=True)
    return images[0]["ImageId"]


def ensure_key_pair(region: str) -> tuple[str, str]:
    """Create or reuse an agentflow SSH key pair.

    Returns ``(key_name, identity_file_path)``.
    """
    import boto3

    key_name = "agentflow"
    key_path = os.path.expanduser(f"~/.agentflow/keys/{region}.pem")

    ec2 = boto3.client("ec2", region_name=region)
    existing = ec2.describe_key_pairs(
        Filters=[{"Name": "key-name", "Values": [key_name]}],
    )["KeyPairs"]

    if existing and os.path.exists(key_path):
        return key_name, key_path

    # Delete stale key pair if the local file is missing
    if existing:
        ec2.delete_key_pair(KeyName=key_name)

    resp = ec2.create_key_pair(KeyName=key_name)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "w") as f:
        f.write(resp["KeyMaterial"])
    os.chmod(key_path, 0o600)
    return key_name, key_path


def collect_local_credentials(agent: str) -> dict[str, str]:
    """Read local agent credentials and return as env vars.

    Reads config files and environment variables for each agent CLI.
    Works for codex (auth.json + config.toml), claude (OAuth from
    .credentials.json), and kimi (env var).
    """
    env: dict[str, str] = {}

    if agent in ("codex", "all"):
        # ~/.codex/auth.json
        auth_path = Path.home() / ".codex" / "auth.json"
        if auth_path.exists():
            try:
                auth = json.loads(auth_path.read_text(encoding="utf-8"))
                if auth.get("OPENAI_API_KEY"):
                    env["OPENAI_API_KEY"] = auth["OPENAI_API_KEY"]
            except (json.JSONDecodeError, OSError):
                pass
        # ~/.codex/config.toml for base_url
        config_path = Path.home() / ".codex" / "config.toml"
        if config_path.exists():
            try:
                for line in config_path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("base_url"):
                        _, _, value = stripped.partition("=")
                        value = value.strip().strip('"').strip("'")
                        if value:
                            env["OPENAI_BASE_URL"] = value
                            break
            except OSError:
                pass
        if os.environ.get("OPENAI_API_KEY"):
            env.setdefault("OPENAI_API_KEY", os.environ["OPENAI_API_KEY"])
        if os.environ.get("OPENAI_BASE_URL"):
            env.setdefault("OPENAI_BASE_URL", os.environ["OPENAI_BASE_URL"])

    if agent in ("claude", "all"):
        # ~/.claude/.credentials.json (OAuth token)
        creds_path = Path.home() / ".claude" / ".credentials.json"
        if creds_path.exists():
            try:
                creds = json.loads(creds_path.read_text(encoding="utf-8"))
                oauth = creds.get("claudeAiOauth", {})
                if isinstance(oauth, dict) and oauth.get("accessToken"):
                    env["ANTHROPIC_API_KEY"] = oauth["accessToken"]
            except (json.JSONDecodeError, OSError):
                pass
        if os.environ.get("ANTHROPIC_API_KEY"):
            env.setdefault("ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"])
        if os.environ.get("ANTHROPIC_BASE_URL"):
            env.setdefault("ANTHROPIC_BASE_URL", os.environ["ANTHROPIC_BASE_URL"])

    if agent in ("kimi", "all"):
        if os.environ.get("KIMI_API_KEY"):
            env["KIMI_API_KEY"] = os.environ["KIMI_API_KEY"]
        if os.environ.get("MOONSHOT_API_KEY"):
            env["MOONSHOT_API_KEY"] = os.environ["MOONSHOT_API_KEY"]

    return env
