def issue_stage_receipt(self, stage, task_id="", run_id="", revision=0, artifact_digest=""):
    subject = f"stage_complete:{task_id}:{run_id}:{stage}"
    return subject
