"""
Optional NVIDIA-GPU LoRA training entry point.

Run only after manually reviewing training/data/style_examples.jsonl.
Daily knowledge freshness does NOT depend on this training; new videos become
searchable immediately through ingestion.

Example:
  pip install -r training/requirements.txt
  python training/train_lora.py \
    --model Qwen/Qwen3-4B \
    --data training/data/style_examples.jsonl \
    --output training/output/bhajan-style-lora
"""
import argparse
from datasets import load_dataset
from transformers import AutoTokenizer
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-4B")
    ap.add_argument("--data", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--bf16", action="store_true")
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    ds = load_dataset("json", data_files=args.data, split="train")

    def format_row(example):
        return {
            "text": tok.apply_chat_template(
                example["messages"],
                tokenize=False,
                add_generation_prompt=False,
            )
        }

    ds = ds.map(format_row)

    peft = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "up_proj", "down_proj", "gate_proj",
        ],
    )

    cfg = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        learning_rate=1e-4,
        logging_steps=10,
        save_steps=250,
        bf16=args.bf16,
        gradient_checkpointing=True,
        report_to="none",
        dataset_text_field="text",
        max_length=2048,
        packing=True,
    )

    trainer = SFTTrainer(
        model=args.model,
        args=cfg,
        train_dataset=ds,
        peft_config=peft,
    )
    trainer.train()
    trainer.save_model(args.output)


if __name__ == "__main__":
    main()
