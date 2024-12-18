# -*- coding: utf-8 -*-
"""parta_projectb.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1dRFEj8B0liMAjZ_AlRKZy-dzP2t1ki_C
"""

from google.colab import drive
drive.mount('gdrive')

# Paths
data_path = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/"
annotations_file = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/annotations.csv"
img_dir = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/images"

!pip install ptflops

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, models
import pandas as pd
from PIL import Image
import os
import time
from einops import rearrange, repeat
from torchvision.models import resnet18, ResNet18_Weights
import math
from ptflops import get_model_complexity_info
from sklearn.metrics import confusion_matrix, classification_report, precision_recall_fscore_support
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np

"""Baseline Model"""

class MHISTDataset(Dataset):
    """Dataset class for MHIST data."""
    def __init__(self, annotations_file, img_dir, partition, transform=None):
        self.annotations = pd.read_csv(annotations_file)
        self.annotations = self.annotations[self.annotations['Partition'] == partition]
        self.img_dir = img_dir
        self.transform = transform
        self.label_map = {'SSA': 0, 'HP': 1}

    def __len__(self):
        return len(self.annotations)

    def __getitem__(self, idx):
        img_path = os.path.join(self.img_dir, self.annotations.iloc[idx, 0])
        image = Image.open(img_path).convert("RGB")
        label = self.label_map[self.annotations.iloc[idx, 1]]
        if self.transform:
            image = self.transform(image)
        return image, label

class BaselineModel(nn.Module):
    """Simple ResNet18-based classification model."""
    def __init__(self, num_classes):
        super().__init__()

        # Load pretrained ResNet18
        self.resnet = resnet18(weights=ResNet18_Weights.DEFAULT)

        # Replace the final layer
        num_features = self.resnet.fc.in_features
        self.resnet.fc = nn.Sequential(
            nn.Linear(num_features, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        return self.resnet(x)

def train_baseline_model(annotations_file, img_dir):
    """Train and evaluate the baseline model."""
    # Basic transforms without augmentation
    transform = transforms.Compose([
        transforms.Resize((128, 128)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])

    # Create datasets and dataloaders
    train_dataset = MHISTDataset(annotations_file, img_dir, partition='train', transform=transform)
    test_dataset = MHISTDataset(annotations_file, img_dir, partition='test', transform=transform)

    batch_size = 16
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=2, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=True)

    # Initialize model and training components
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    num_classes = len(train_dataset.annotations['Majority Vote Label'].unique())
    model = BaselineModel(num_classes=num_classes).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    optimizer = optim.Adam(model.parameters(), lr=0.0003)

    # Training loop
    print("Starting training...")
    num_epochs = 10
    training_start_time = time.time()
    training_losses = []
    training_accuracies = []

    for epoch in range(num_epochs):
        model.train()
        epoch_loss = 0
        correct = 0
        total = 0

        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            epoch_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()

        avg_loss = epoch_loss / len(train_loader)
        accuracy = 100 * correct / total
        training_losses.append(avg_loss)
        training_accuracies.append(accuracy)

        print(f'Epoch {epoch+1}: Loss = {avg_loss:.4f}, Accuracy = {accuracy:.2f}%')

    training_time = time.time() - training_start_time

    # Enhanced evaluation
    print("\nEvaluating model...")
    model.eval()
    test_loss = 0
    all_preds = []
    all_labels = []

    testing_start_time = time.time()
    with torch.no_grad():
        for images, labels in test_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)

            test_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)

            # Store predictions and labels for metrics
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    testing_time = time.time() - testing_start_time
    avg_test_loss = test_loss / len(test_loader)

    # Convert lists to numpy arrays
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)

    # Calculate comprehensive metrics
    accuracy = 100 * (all_preds == all_labels).mean()
    precision, recall, f1, _ = precision_recall_fscore_support(all_labels, all_preds, labels=[0, 1], average=None)

    # Print detailed results
    print("\nTest Results:")
    print(f"Test Loss: {avg_test_loss:.4f}")
    print(f"Overall Accuracy: {accuracy:.2f}%")
    # Print full classification report
    print("\nDetailed Classification Report:")
    print(classification_report(all_labels, all_preds, target_names=['SSA', 'HP'], digits=4))


    # Print timing and complexity metrics
    print(f"\nTraining Time: {training_time:.2f}s")
    print(f"Testing Time: {testing_time:.2f}s")

    # Calculate model complexity
    flops, params = get_model_complexity_info(model.cpu(), (3, 128, 128), as_strings=False, print_per_layer_stat=False)
    print(f"Model FLOPs: {flops:e}")

    # Return comprehensive metrics dictionary
    return {
        'test_loss': avg_test_loss,
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'training_time': training_time,
        'testing_time': testing_time,
        'flops': flops,
        'confusion_matrix': confusion_matrix(all_labels, all_preds),
        'training_history': {
            'losses': training_losses,
            'accuracies': training_accuracies
        }
    }

if __name__ == "__main__":
    annotations_file = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/annotations.csv"
    img_dir = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/images"
    metrics = train_baseline_model(annotations_file, img_dir)

"""Hybrid model: ResNet18 + Mamba"""

class MHISTDataset(Dataset):
    """Dataset class for MHIST data."""
    def __init__(self, annotations_file, img_dir, partition, transform=None):
        self.annotations = pd.read_csv(annotations_file)
        self.annotations = self.annotations[self.annotations['Partition'] == partition]
        self.img_dir = img_dir
        self.transform = transform
        self.label_map = {'SSA': 0, 'HP': 1}

    def __len__(self):
        return len(self.annotations)

    def __getitem__(self, idx):
        img_path = os.path.join(self.img_dir, self.annotations.iloc[idx, 0])
        image = Image.open(img_path).convert("RGB")
        label = self.label_map[self.annotations.iloc[idx, 1]]
        if self.transform:
            image = self.transform(image)
        return image, label

class Mamba(nn.Module):
    """Mamba layer implementation for sequential modeling."""
    def __init__(self, d_model, d_state=16, d_conv=4, expand=2.0, dt_rank=16,
                 dt_min=0.001, dt_max=0.1, dt_init="random", dt_scale=1.0,
                 dt_init_floor=1e-4, conv_bias=True, bias=False, device=None, dtype=None):
        factory_kwargs = {"device": device, "dtype": dtype}
        super().__init__()
        self.d_model = d_model
        self.d_state = d_state
        self.d_conv = d_conv
        self.expand = expand
        self.d_inner = int(self.expand * self.d_model)
        self.dt_rank = dt_rank

        # Initialize layers
        self.in_proj = nn.Linear(self.d_model, self.d_inner * 2, bias=bias, **factory_kwargs)
        self.conv1d = nn.Conv1d(
            in_channels=self.d_inner,
            out_channels=self.d_inner,
            bias=conv_bias,
            kernel_size=d_conv,
            groups=self.d_inner,
            padding=d_conv - 1,
            **factory_kwargs,
        )
        self.act = nn.SiLU()
        self.x_proj = nn.Linear(self.d_inner, self.dt_rank + self.d_state * 2, bias=False, **factory_kwargs)
        self.dt_proj = nn.Linear(self.dt_rank, self.d_inner, bias=True, **factory_kwargs)

        # Initialize dt parameters
        dt_init_std = self.dt_rank**-0.5 * dt_scale
        if dt_init == "random":
            nn.init.uniform_(self.dt_proj.weight, -dt_init_std, dt_init_std)

        dt = torch.exp(
            torch.rand(self.d_inner, **factory_kwargs) * (math.log(dt_max) - math.log(dt_min))
            + math.log(dt_min)
        ).clamp(min=dt_init_floor)
        inv_dt = dt + torch.log(-torch.expm1(-dt))
        with torch.no_grad():
            self.dt_proj.bias.copy_(inv_dt)

        # Initialize SSM parameters
        A = torch.arange(1, self.d_state + 1, dtype=torch.float32, device=device)
        A = A.expand(self.d_inner, -1)
        self.A_log = nn.Parameter(torch.log(A))
        self.D = nn.Parameter(torch.ones(self.d_inner, device=device))
        self.out_proj = nn.Linear(self.d_inner, self.d_model, bias=bias, **factory_kwargs)

    def forward(self, x):
        batch_size, seq_len, _ = x.shape

        # Input projection and reshaping
        xz = self.in_proj(x)
        xz = xz.view(batch_size, seq_len, 2, self.d_inner).permute(0, 2, 3, 1)
        x, z = xz[:, 0], xz[:, 1]

        # Convolution and activation
        x = self.act(self.conv1d(x)[..., :seq_len])

        # Project and split parameters
        x_dbl = self.x_proj(x.transpose(1, 2))
        dt, B, C = torch.split(x_dbl, [self.dt_rank, self.d_state, self.d_state], dim=-1)
        dt = self.dt_proj(dt).transpose(1, 2)

        # Compute SSM parameters
        A = -torch.exp(self.A_log.float())
        dt = F.softplus(dt + self.dt_proj.bias[None, :, None].float())

        # Initialize state and output
        y = torch.zeros_like(x)
        hidden = torch.zeros((batch_size, self.d_inner, self.d_state), device=x.device, dtype=x.dtype)

        # Selective scan
        for t in range(seq_len):
            hidden = hidden * torch.exp(dt[:, :, t:t+1] * A.unsqueeze(0))
            hidden = hidden + x[:, :, t:t+1] * B[:, t:t+1].view(batch_size, 1, self.d_state)

            hidden_reshaped = hidden.view(batch_size, self.d_inner, self.d_state)
            C_t = C[:, t].view(batch_size, self.d_state)
            out_t = torch.bmm(hidden_reshaped, C_t.unsqueeze(-1)).squeeze(-1)
            y[:, :, t] = out_t + self.D * x[:, :, t]

        # Final processing
        y = y * self.act(z)
        y = y.transpose(1, 2)
        return self.out_proj(y)

class HybridModel(nn.Module):
    """Hybrid model combining ResNet backbone with Mamba sequential processing."""
    def __init__(self, num_classes):
        super().__init__()

        # CNN Backbone
        resnet = resnet18(weights=ResNet18_Weights.DEFAULT)
        self.backbone = nn.Sequential(*list(resnet.children())[:-1])

        # Feature processing
        self.norm = nn.LayerNorm(512)
        self.mamba = Mamba(
            d_model=512,
            d_state=8,
            d_conv=4,
            expand=1.0,
            dt_rank=8
        )

        # Classification head
        self.classifier = nn.Sequential(
            nn.Linear(512, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        features = self.backbone(x)
        features = features.squeeze(-1).squeeze(-1)
        features = self.norm(features)
        features = features.unsqueeze(1)
        mamba_out = self.mamba(features)
        pooled = mamba_out.mean(dim=1)
        return self.classifier(pooled)


def train_hybrid_model(annotations_file, img_dir):
    """Train and evaluate the hybrid model."""
    # Basic transforms without augmentation
    transform = transforms.Compose([
        transforms.Resize((128, 128)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])

    # Create datasets and dataloaders
    train_dataset = MHISTDataset(annotations_file, img_dir, partition='train', transform=transform)
    test_dataset = MHISTDataset(annotations_file, img_dir, partition='test', transform=transform)

    batch_size = 16
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=2, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False, num_workers=2, pin_memory=True)

    # Initialize model and training components
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    num_classes = len(train_dataset.annotations['Majority Vote Label'].unique())
    model = HybridModel(num_classes=num_classes).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    optimizer = optim.Adam(model.parameters(), lr=0.0003)

    # Training loop
    print("Starting training...")
    num_epochs = 10
    training_start_time = time.time()
    training_losses = []
    training_accuracies = []

    for epoch in range(num_epochs):
        model.train()
        epoch_loss = 0
        correct = 0
        total = 0

        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            epoch_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()

        avg_loss = epoch_loss / len(train_loader)
        accuracy = 100 * correct / total
        training_losses.append(avg_loss)
        training_accuracies.append(accuracy)

        print(f'Epoch {epoch+1}: Loss = {avg_loss:.4f}, Accuracy = {accuracy:.2f}%')

    training_time = time.time() - training_start_time

    # Evaluation
    print("\nEvaluating model...")
    model.eval()
    test_loss = 0
    all_preds = []
    all_labels = []

    testing_start_time = time.time()
    with torch.no_grad():
        for images, labels in test_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)

            test_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            all_preds.extend(predicted.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    testing_time = time.time() - testing_start_time
    avg_test_loss = test_loss / len(test_loader)
    # Convert lists to numpy arrays
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)

    # Calculate comprehensive metrics
    accuracy = 100 * (all_preds == all_labels).mean()
    precision, recall, f1, _ = precision_recall_fscore_support(all_labels, all_preds, labels=[0, 1], average=None)

    # Print detailed results
    print("\nTest Results:")
    print(f"Test Loss: {avg_test_loss:.4f}")
    print(f"Overall Accuracy: {accuracy:.2f}%")

     # Print full classification report
    print("\nDetailed Classification Report:")
    print(classification_report(all_labels, all_preds,  target_names=['SSA', 'HP'], digits=4))

    # Training/Testing time and model complexity
    print(f"\nTraining Time: {training_time:.2f}s")
    print(f"Testing Time: {testing_time:.2f}s")

    # Calculate FLOPs
    flops, params = get_model_complexity_info(model.cpu(), (3, 128, 128), as_strings=False, print_per_layer_stat=False)
    print(f"Model FLOPs: {flops:e}")

    # Return all metrics for comparison
    return {
        'test_loss': avg_test_loss,
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'training_time': training_time,
        'testing_time': testing_time,
        'flops': flops,
        'confusion_matrix': confusion_matrix(all_labels, all_preds),
        'training_history': {
            'losses': training_losses,
            'accuracies': training_accuracies
        }
    }

if __name__ == "__main__":
    annotations_file = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/annotations.csv"
    img_dir = "/content/gdrive/MyDrive/submission_files1/mhist_dataset/images"
    metrics = train_hybrid_model(annotations_file, img_dir)