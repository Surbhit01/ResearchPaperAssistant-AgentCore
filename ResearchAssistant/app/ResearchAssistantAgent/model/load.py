from strands.models.bedrock import BedrockModel
import os

DEFAULT_MODEL_ID = "us.amazon.nova-lite-v1:0"

def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(model_id=os.environ.get("MODEL_ID", DEFAULT_MODEL_ID))
