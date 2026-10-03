"""Fine-tune ViT-B/16 on ImageNet-1k (Table 3). Requires a CUDA GPU."""
import argparse

import torch
import timm
from torchvision import datasets, transforms

IMAGENET_ROOT = "/data/imagenet"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=512)
    args = parser.parse_args()

    tf = transforms.Compose([transforms.RandomResizedCrop(224), transforms.ToTensor()])
    train = datasets.ImageNet(IMAGENET_ROOT, split="train", transform=tf)
    loader = torch.utils.data.DataLoader(train, batch_size=args.batch_size, shuffle=True)

    model = timm.create_model("vit_base_patch16_224", pretrained=True, num_classes=1000).cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    for epoch in range(args.epochs):
        for xb, yb in loader:
            xb, yb = xb.cuda(), yb.cuda()
            loss = torch.nn.functional.cross_entropy(model(xb), yb)
            opt.zero_grad()
            loss.backward()
            opt.step()


if __name__ == "__main__":
    main()
