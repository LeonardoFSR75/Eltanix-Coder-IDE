# Copyright 2025 Cisco Systems, Inc. and its affiliates
#
# SPDX-License-Identifier: Apache-2.0

from datasets import Dataset
import re
from transformers import AutoTokenizer
import json
import torch
import pandas as pd
from sentence_transformers import InputExample

class ModernBertDataset(Dataset):
    def __init__(self, parquet_path="./opensource_data/data_pretrain.parquet", n=None):
        """
        Args:
            parquet_path (str): Path to the single .parquet file.
            n (int, optional): If provided, randomly sample n rows from the file.
        """
        self.tokenizer = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-base")

        # Load the parquet file (must contain a column named "text")
        df = pd.read_parquet(parquet_path)

        # Sample n rows if requested
        if n is not None and n < len(df):
            df = df.sample(n=n, random_state=42)

        # Clean the text
        self.txt_data = [self.clean_text(t) for t in df["text"].astype(str).tolist()]

    def clean_text(self, text):
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)   # remove markdown headings
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)             # bold -> plain
        text = re.sub(r"\*(.*?)\*", r"\1", text)                 # italic -> plain
        text = re.sub(r"\[.*?\]\(.*?\)", "", text)               # links -> remove
        text = re.sub(r"`([^`]*)`", r"\1", text)                 # inline code -> plain
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)   # code blocks -> remove
        text = re.sub(r"\n+", "\n", text)                        # collapse multiple newlines
        text = re.sub(r"\s{2,}", " ", text)                      # collapse extra spaces
        return text.strip()

    def __getitem__(self, idx):
        curr_text = self.txt_data[idx]
        encoded = self.tokenizer(
            curr_text,
            padding="max_length",
            truncation=True,
            max_length=1024,
            return_tensors="pt",
        )
        return {
            "input_ids": encoded["input_ids"].squeeze(0),
            "attention_mask": encoded["attention_mask"].squeeze(0),
        }

    def __len__(self):
        return len(self.txt_data)

class ContrastiveLearningDataset:
    def __init__(self, parquet_path="./opensource_data/data_sentence_pairs.parquet"):
        df = pd.read_parquet(parquet_path, engine="pyarrow")
        self.txt_data = list(zip(df["sentence1"], df["sentence2"]))

    def __getitem__(self, idx):
        return self.txt_data[idx]  # already a tuple

    def __len__(self):
        return len(self.txt_data)

class Eval_ContrastiveDataset:
    def __init__(self, parquet_path="./opensource_data/data_sentence_pairs_test.parquet"):
        df = pd.read_parquet(parquet_path, engine="pyarrow")
        self.txt_data = list(zip(df["sentence1"], df["sentence2"]))

    def __getitem__(self, idx):
        return self.txt_data[idx]

    def __len__(self):
        return len(self.txt_data)

class Mrr_ContrastiveLearningDataset:
    def __init__(self, parquet_path="./opensource_data/data_sentence_pairs.parquet"):
        df = pd.read_parquet(parquet_path, engine="pyarrow")
        self.txt_data = list(zip(df["sentence1"], df["sentence2"]))

    def __getitem__(self, idx):
        curr_txt = self.txt_data[idx]
        return InputExample(texts=[curr_txt[0], curr_txt[1]])
    
    def __len__(self):
        return len(self.txt_data)

class NerDataset():
    def __init__(self, data_path="./opensource_data/data_NER_test.json", mode="train"):
        self.txt_data = list()
        self.ner_tags = list()
        self.load_data(data_path)
        assert len(self.ner_tags) == len(self.txt_data)
        # Run tokenization step separately
        self.tokenizer = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-base")
        self.tokenized_inputs, self.labels = self.tokenize_and_align_labels()
    
    def tokenize_and_align_labels(self):
        """Tokenizes txt_data and aligns NER tags with subword tokens."""
        tokenized_inputs = self.tokenizer(
            self.txt_data,
            is_split_into_words=True,
            truncation=True,
            max_length=1024,
        )

        labels = []
        # Align labels with word pieces
        for i, ner_tags_for_example in enumerate(self.ner_tags):
            word_ids = tokenized_inputs.word_ids(batch_index=i)
            current_labels = []
            previous_word_idx = None
            for word_idx in word_ids:
                if word_idx is None:
                    current_labels.append(-100)
                elif word_idx != previous_word_idx:
                    current_labels.append(ner_tags_for_example[word_idx])
                else:
                    current_labels.append(-100)
                previous_word_idx = word_idx
            labels.append(current_labels)

        return tokenized_inputs, labels
        
    def __getitem__(self, idx):
        return {
            'input_ids': torch.tensor(self.tokenized_inputs['input_ids'][idx], dtype=torch.long),
            'attention_mask': torch.tensor(self.tokenized_inputs['attention_mask'][idx], dtype=torch.long),
            'labels': torch.tensor(self.labels[idx], dtype=torch.long)
        }
    def __len__(self):
        return len(self.txt_data)
    
    def save_data(self, path, n=None):
        """Save txt_data, ner_tags, and label metadata to JSON file."""
        if not n:
            n = len(self.txt_data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "txt_data": self.txt_data[:n],
                "ner_tags": self.ner_tags[:n],
                "num_labels": self.num_labels
            }, f)

    def load_data(self, path):
        """Load txt_data, ner_tags, and label metadata from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.txt_data = data["txt_data"]
        self.ner_tags = data["ner_tags"]
        self.num_labels = data["num_labels"]

class SentimentVulnerabilityDataset():
    def __init__(self, parquet_path="./opensource_data/data_vuln_dataset.parquet"):
        self.txt_data = list()
        df = pd.read_parquet(parquet_path, engine="pyarrow")
        self.txt_data = list(zip(df["code"], df["label"]))
    def __getitem__(self, idx):
        curr_txt = self.txt_data[idx]
        return curr_txt[0], curr_txt[1]
    def __len__(self):
        return len(self.txt_data)

class Eval_SentimentVulnerabilityDataset():
    def __init__(self, parquet_path="./opensource_data/data_vuln_dataset_test.parquet"):
        self.txt_data = list()
        df = pd.read_parquet(parquet_path, engine="pyarrow")
        self.txt_data = list(zip(df["code"], df["label"]))
    def __getitem__(self, idx):
        curr_txt = self.txt_data[idx]
        return curr_txt[0], curr_txt[1]
    def __len__(self):
        return len(self.txt_data)
