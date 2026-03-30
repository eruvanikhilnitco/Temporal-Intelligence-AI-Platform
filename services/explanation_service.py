class ExplanationService:
    def build_explanation(self, lifecycle_id: str) -> str:
        return (
            "Risk is driven by recent change orders and invoice variance "
            "relative to the original purchase order."
        )
