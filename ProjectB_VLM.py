# -*- coding: utf-8 -*-
"""projectb_VLM.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1mFghmS-4FStrzarMWn9GFVY_weZZbM9T
"""

from google.colab import drive
drive.mount('gdrive')

import warnings
warnings.filterwarnings("ignore")

!pip install torchprofile

import torch
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence
from PIL import Image
from tqdm import tqdm
import os
import time
from torchprofile import profile_macs



class BaselineTokenProcessor(nn.Module):
    def __init__(self, img_size=112, patch_size=16, embed_dim=64):
        super().__init__()
        self.img_size = img_size
        self.patch_size = patch_size
        self.num_patches = (img_size // patch_size) ** 2
        self.embed_dim = embed_dim

        self.patch_embed = nn.Linear(patch_size * patch_size * 3, embed_dim)
        self.projector = nn.Linear(embed_dim, embed_dim)

    def forward(self, images):
        patches = images.unfold(2, self.patch_size, self.patch_size)\
                  .unfold(3, self.patch_size, self.patch_size)\
                  .reshape(-1, self.num_patches, self.patch_size * self.patch_size * 3)
        tokens = self.patch_embed(patches)
        projected = self.projector(tokens)
        pooled = projected.mean(dim=1)  # Pool features
        return pooled  # Output pooled features for alignment


# Multimodal Token Processor
class MultimodalTokenProcessor(nn.Module):
    def __init__(self, img_size=112, patch_size=16, embed_dim=64, text_vocab_size=100, text_dim=50):
        super().__init__()
        self.img_size = img_size
        self.patch_size = patch_size
        self.num_patches = (img_size // patch_size) ** 2
        self.embed_dim = embed_dim

        # Visual token processing
        self.patch_embed = nn.Linear(patch_size * patch_size * 3, embed_dim)
        self.importance_scorer = nn.Sequential(
            nn.Linear(embed_dim, embed_dim // 4),
            nn.GELU(),
            nn.Linear(embed_dim // 4, 1)
        )

        # Text token processing
        self.text_embedding = nn.Embedding(text_vocab_size, text_dim)
        self.text_projector = nn.Linear(text_dim, embed_dim)
        self.alignment_layer = nn.Bilinear(embed_dim, embed_dim, 1)

    def forward(self, images, captions):
        # Process visual tokens
        patches = images.unfold(2, self.patch_size, self.patch_size)\
                  .unfold(3, self.patch_size, self.patch_size)\
                  .reshape(-1, self.num_patches, self.patch_size * self.patch_size * 3)
        visual_tokens = self.patch_embed(patches)

        importance_scores = self.importance_scorer(visual_tokens).squeeze(-1)
        k = int(visual_tokens.shape[1] * 0.5)
        _, indices = torch.topk(importance_scores, k, dim=1)
        pruned_tokens = torch.gather(visual_tokens, 1, indices.unsqueeze(-1).expand(-1, -1, self.embed_dim))

        # Process text tokens
        embedded_captions = self.text_embedding(captions)
        text_embeddings = self.text_projector(embedded_captions.mean(dim=1))

        # Align tokens
        alignment_scores = self.alignment_layer(pruned_tokens.mean(dim=1), text_embeddings)

        return alignment_scores


# Dataset Preparation
class FlickrDataset(Dataset):
    def __init__(self, image_folder, captions, transform=None, tokenizer=None, vocab=None):
        self.image_folder = image_folder
        self.captions = captions
        self.transform = transform
        self.tokenizer = tokenizer
        self.vocab = vocab

    def __len__(self):
        return len(self.captions)

    def __getitem__(self, idx):
        img_id = list(self.captions.keys())[idx]
        captions = self.captions[img_id]
        image_path = os.path.join(self.image_folder, img_id)
        image = Image.open(image_path).convert("RGB")

        if self.transform:
            image = self.transform(image)

        tokenized_caption = self.tokenizer(captions[0].lower())
        caption_vector = [self.vocab.get(token, 0) for token in tokenized_caption]
        caption_vector = torch.tensor(caption_vector, dtype=torch.long)

        return image, caption_vector

import random

def setup_data(sample_ratio=0.4):  # Add `sample_ratio` argument to control dataset size
    # Define paths
    image_folder = "/content/gdrive/MyDrive/data/flickr8k/Flicker8k_Dataset"
    caption_file = "/content/gdrive/MyDrive/data/flickr8k/flickr8k_text/Flickr8k.token.txt"
    train_split_file = "/content/gdrive/MyDrive/data/flickr8k/flickr8k_text/Flickr_8k.trainImages.txt"
    test_split_file = "/content/gdrive/MyDrive/data/flickr8k/flickr8k_text/Flickr_8k.testImages.txt"

    # Define transformations
    transform = transforms.Compose([
        transforms.Resize((112, 112)),
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,))
    ])

    # Use a tokenizer and create a vocab dynamically
    tokenizer = lambda x: x.split()
    vocab = {"<PAD>": 0, "<UNK>": 1}
    with open(caption_file, 'r') as f:
        for line in f:
            _, caption = line.strip().split('\t')
            for word in tokenizer(caption.lower()):
                if word not in vocab:
                    vocab[word] = len(vocab)

    def filter_captions(image_list, caption_file):
        captions = {}
        with open(caption_file, 'r') as f:
            for line in f:
                img_id, caption = line.strip().split('\t')
                img_id = img_id.split('#')[0]
                if img_id in image_list:
                    if img_id not in captions:
                        captions[img_id] = []
                    captions[img_id].append(caption)
        return captions

    # Load train and test splits
    with open(train_split_file, 'r') as f:
        train_images = set(line.strip() for line in f)
    with open(test_split_file, 'r') as f:
        test_images = set(line.strip() for line in f)

    # Randomly sample a subset of the dataset
    train_images = random.sample(train_images, int(len(train_images) * sample_ratio))
    test_images = random.sample(test_images, int(len(test_images) * sample_ratio))

    train_captions = filter_captions(train_images, caption_file)
    test_captions = filter_captions(test_images, caption_file)

    # Create train and test datasets
    train_dataset = FlickrDataset(image_folder, train_captions, transform, tokenizer, vocab)
    test_dataset = FlickrDataset(image_folder, test_captions, transform, tokenizer, vocab)

    # Create dataloaders
    train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True, collate_fn=collate_fn)
    test_loader = DataLoader(test_dataset, batch_size=16, shuffle=False, collate_fn=collate_fn)

    return train_loader, test_loader, len(vocab)

class CosineSimilarityLoss(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, outputs, targets):
        outputs = nn.functional.normalize(outputs, p=2, dim=-1)
        targets = nn.functional.normalize(targets, p=2, dim=-1)
        return 1 - nn.functional.cosine_similarity(outputs, targets, dim=-1).mean()


def collate_fn(batch):
    images, captions = zip(*batch)
    images = torch.stack(images)
    captions = pad_sequence(captions, batch_first=True, padding_value=0)
    return images, captions


def train_model(model, train_loader, device='cuda', epochs=10, is_baseline=False):
    criterion = CosineSimilarityLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    model = model.to(device)
    model.train()

    total_training_time = 0
    for epoch in range(epochs):
        start_time = time.time()
        running_loss = 0.0
        for images, captions in tqdm(train_loader):
            images, captions = images.to(device), captions.to(device)

            optimizer.zero_grad()
            if is_baseline:
                outputs = model(images)  # Baseline processes only images
                targets = captions.float().mean(dim=1, keepdim=True)
            else:
                outputs = model(images, captions)  # Optimized model processes both
                targets = captions.float().mean(dim=1, keepdim=True)

            # Ensure targets match outputs' shape
            if targets.shape[1] < outputs.shape[1]:
                targets = targets.expand(-1, outputs.shape[1])

            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

        epoch_time = time.time() - start_time
        total_training_time += epoch_time
        print(f"Epoch {epoch + 1}: Loss = {running_loss / len(train_loader):.4f}, Time = {epoch_time:.2f}s")

    return total_training_time


def test_model(model, test_loader, device='cuda', is_baseline=False):
    criterion = CosineSimilarityLoss()
    model.eval()

    total_loss = 0.0
    start_time = time.time()

    with torch.no_grad():
        for images, captions in tqdm(test_loader):
            images, captions = images.to(device), captions.to(device)

            if is_baseline:
                outputs = model(images)
                targets = captions.float().mean(dim=1, keepdim=True)
            else:
                outputs = model(images, captions)
                targets = captions.float().mean(dim=1, keepdim=True)

            # Ensure targets match outputs' shape
            if targets.shape[1] < outputs.shape[1]:
                targets = targets.expand(-1, outputs.shape[1])

            loss = criterion(outputs, targets)
            total_loss += loss.item()

    total_testing_time = time.time() - start_time
    avg_loss = total_loss / len(test_loader)
    print(f"Test Loss = {avg_loss:.4f}, Time = {total_testing_time:.2f}s")
    return avg_loss, total_testing_time


def calculate_flops(model, input_shape, is_baseline=False, vocab_size=None):
    model = model.to('cuda')
    dummy_images = torch.randn(input_shape).to('cuda')
    if is_baseline:
        # For baseline model, only pass images
        macs = profile_macs(model, (dummy_images,))
    else:
        # For multimodal model, generate dummy captions
        assert vocab_size is not None, "vocab_size must be provided for the optimized model."
        dummy_captions = torch.randint(0, vocab_size, (input_shape[0], 15)).to('cuda')
        macs = profile_macs(model, (dummy_images, dummy_captions))
    return macs * 2  # FLOPS = 2 * MACs

def main():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    train_loader, test_loader, vocab_size = setup_data()

    baseline_model = BaselineTokenProcessor()
    optimized_model = MultimodalTokenProcessor(text_vocab_size=vocab_size)

    print("Training Baseline Model...")
    baseline_train_time = train_model(baseline_model, train_loader, device, is_baseline=True)
    baseline_loss, baseline_test_time = test_model(baseline_model, test_loader, device, is_baseline=True)
    baseline_flops = calculate_flops(baseline_model, (16, 3, 112, 112), is_baseline=True)

    print("\nTraining Optimized Model...")
    optimized_train_time = train_model(optimized_model, train_loader, device, is_baseline=False)
    optimized_loss, optimized_test_time = test_model(optimized_model, test_loader, device, is_baseline=False)
    optimized_flops = calculate_flops(optimized_model, (16, 3, 112, 112), vocab_size=vocab_size, is_baseline=False)

    # Calculate Lossy-ness
    lossy_ness = (baseline_loss - optimized_loss) / baseline_loss

    print("\nResults Summary:")
    print(f"Baseline Model - Train Time: {baseline_train_time:.2f}s, Test Time: {baseline_test_time:.2f}s, FLOPS: {baseline_flops}")
    print(f"Optimized Model - Train Time: {optimized_train_time:.2f}s, Test Time: {optimized_test_time:.2f}s, FLOPS: {optimized_flops}")
    print(f"Lossy-ness Metric: {lossy_ness:.4f}")

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()