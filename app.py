# model definition 

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import numpy as np
import matplotlib.pyplot as plt
import torch.optim as optim

from torch.autograd import Variable
from torchvision import datasets, transforms
from torch.autograd import Variable

nclasses = 43 # GTSRB has 43 classes
DEBUG = False

def gaussian_filter(kernel_shape):
    x = np.zeros(kernel_shape, dtype='float32')
    def gauss(x, y, sigma=2.0):
        Z = 2 * np.pi * sigma ** 2
        return  1. / Z * np.exp(-(x ** 2 + y ** 2) / (2. * sigma ** 2))
    mid = np.floor(kernel_shape[-1] / 2.)
    for kernel_idx in range(0, kernel_shape[1]):
        for i in range(0, kernel_shape[2]):
            for j in range(0, kernel_shape[3]):
                x[0, kernel_idx, i, j] = gauss(i - mid, j - mid)
    return x / np.sum(x)

def LCN(image_tensor, gaussian, mid):
    filtered= gaussian(image_tensor)
    centered_image = image_tensor - filtered[:,:,mid:-mid,mid:-mid]
    sum_sqr_XX = gaussian(centered_image.pow(2))
    denom = sum_sqr_XX[:,:,mid:-mid,mid:-mid].sqrt()
    per_img_mean = denom.mean()
    divisor = torch.max(per_img_mean, denom)
    divisor = np.maximum(divisor.detach().cpu().numpy(), 1e-4)
    new_image = centered_image.detach().cpu() / divisor
    if DEBUG: # visualize what the network sees
        plt.imshow(np.transpose(filtered[0].detach().cpu().numpy(),
                   (1, 2, 0)).reshape(filtered.shape[2], filtered.shape[3]))
        plt.title('Gaussian')
        plt.show()
        print('GAUSSIAN', filtered)
        print('LCN', new_image)
        plt.imshow(np.transpose(new_image[0, :3].detach().cpu().numpy(),
                   (1, 2, 0)))
        plt.title('LCN')
        plt.show()
    return new_image.cuda()


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(3, 200, kernel_size=7 ,stride=1, padding=2)
        self.maxpool1 = nn.MaxPool2d(2, stride=2 , ceil_mode=True)
        self.gfilter1 = torch.Tensor(gaussian_filter((1,200,9,9)) )
        self.gaussian1 = nn.Conv2d(in_channels=200, out_channels=200,
                            kernel_size=9  , padding= 8 , bias=False)
        self.gaussian1.weight.data = self.gfilter1
        self.gaussian1.weight.requires_grad = False
        self.conv2 = nn.Conv2d(200, 250, kernel_size=4 ,stride=1, padding=2)
        self.maxpool2 = nn.MaxPool2d(2, stride=2 , ceil_mode=True)
        self.gfilter2 = torch.Tensor(gaussian_filter((1,250,9,9)) )
        self.gaussian2  = nn.Conv2d(in_channels=250, out_channels=250,
                            kernel_size=9  , padding= 8 , bias=False)
        self.gaussian2.weight.data = self.gfilter2
        self.gaussian2.weight.requires_grad = False
        self.conv3 = nn.Conv2d(250, 350, kernel_size=4 ,stride=1, padding=2)
        self.maxpool3 = nn.MaxPool2d(2, stride=2)
        self.gfilter3 = torch.Tensor(gaussian_filter((1,350,9,9)) )
        self.gaussian3  = nn.Conv2d(in_channels=350, out_channels=350,
                            kernel_size=9  , padding= 8 , bias=False)
        self.gaussian3.weight.data = self.gfilter3
        self.gaussian3.weight.requires_grad = False
        self.FC1 = nn.Linear(12600, 400)
        self.FC2 = nn.Linear(400, 43)

        # spatial attention model, spatial transformers layers
        self.st1 = nn.Sequential(
            nn.MaxPool2d(2, stride=2 , ceil_mode=True),
            nn.Conv2d(3, 250, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=True),
            nn.Conv2d(250, 250, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=True)
        )
        self.FC1_ = nn.Sequential(
            nn.Linear(9000, 250),
            nn.ReLU(True),
            nn.Linear( 250 , 6 )
        )
        self.st2 = nn.Sequential(
            nn.MaxPool2d(2, stride=2 , ceil_mode=False),
            nn.Conv2d(200, 150, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=False),
            nn.Conv2d(150, 200, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=False)
        )
        self.FC2_ =  nn.Sequential(
            nn.Linear(800, 300),
            nn.ReLU(True),
            nn.Linear( 300 , 6 )
        )
        self.st3 = nn.Sequential(
            nn.MaxPool2d(2, stride=2 , ceil_mode=False),
            nn.Conv2d(250, 150, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=False),
            nn.Conv2d(150, 200, kernel_size=5 ,stride=1, padding=2),
            nn.ReLU(True),
            nn.MaxPool2d(2, stride=2 , ceil_mode=False)
        )
        self.FC3_ =  nn.Sequential(
            nn.Linear(200, 300),
            nn.ReLU(True),
            nn.Linear( 300 , 6 )
        )
        self.FC1_[2].weight.data.zero_()
        self.FC1_[2].bias.data.copy_(torch.tensor([1, 0, 0, 0, 1, 0], dtype=torch.float))
        self.FC2_[2].weight.data.zero_()
        self.FC2_[2].bias.data.copy_(torch.tensor([1, 0, 0, 0, 1, 0], dtype=torch.float))
        self.FC3_[2].weight.data.zero_()
        self.FC3_[2].bias.data.copy_(torch.tensor([1, 0, 0, 0, 1, 0], dtype=torch.float))

    def forward(self, x):
        # first layer is the Spatial Transformer Layer
        # ST-1
        h1 = self.st1(x)
        h1 = h1.view(-1, 9000)
        h1 = self.FC1_(h1)
        theta1 = h1.view(-1, 2, 3)
        grid1 = F.affine_grid(theta1, x.size())
        x = F.grid_sample(x, grid1)

        # convolution, Relu and Maxpool , SET #1
        x = F.relu(self.conv1(x))
        x =  self.maxpool1(x)

        # paper Says to apply LCN here, but LCN Layer Before Convolution Worked for me better
        # ST-2
        h2 = self.st2(x)
        h2=h2.view(-1,800)
        h2 = self.FC2_(h2)
        theta2 = h2.view(-1, 2, 3)
        grid2 = F.affine_grid(theta2, x.size())
        x = F.grid_sample(x, grid2)

        # LCN Layer : Based on paper implemntation from the github and Yann Lecun Paper 2009
        mid1 = int(np.floor(self.gfilter1.shape[2] / 2.))
        x = LCN(x , self.gaussian1, mid1)

        # convolution, Relu and Maxpool , SET #2
        x = F.relu(self.conv2(x))
        x=  self.maxpool2(x)

        # ST-2
        h3 = self.st3(x)
        h3 = h3.view(-1, 200)
        h3 = self.FC3_(h3)
        theta3 = h3.view(-1, 2, 3)
        grid3 = F.affine_grid(theta3, x.size())
        x = F.grid_sample(x, grid3)

        # LCN Layer : 2
        mid2 = int(np.floor(self.gfilter2.shape[2] / 2.))
        x = LCN(x , self.gaussian2, mid2)

        # convolution, Relu and Maxpool , SET #3
        x = F.relu(self.conv3(x))
        x=  self.maxpool3(x)

        # LCN Layer : 3
        mid3 = int(np.floor(self.gfilter3.shape[2] / 2.))
        x = LCN(x , self.gaussian3, mid3)

        # dimensions in accordance to paper
        y = x.view(-1, 12600)
        y = F.relu(self.FC1(y))
        y = self.FC2(y)
        return F.log_softmax(y, dim=-1)


# app
import streamlit as st
import torch
import numpy as np
from PIL import Image


# Load model
model = Net()
checkpoint = torch.load("/content/model (2).pth", map_location=torch.device('cpu'), weights_only=False)
model.load_state_dict(checkpoint['model_state_dict'])
model.eval()

# Sign names
sign_names = [
    "Speed limit (20km/h)", "Speed limit (30km/h)", "Speed limit (50km/h)",
    "Speed limit (60km/h)", "Speed limit (70km/h)", "Speed limit (80km/h)",
    "End of speed limit (80km/h)", "Speed limit (100km/h)", "Speed limit (120km/h)",
    "No passing", "No passing for vehicles over 3.5 metric tons",
    "Right-of-way at the next intersection", "Priority road", "Yield", "Stop",
    "No vehicles", "Vehicles over 3.5 metric tons prohibited", "No entry",
    "General caution", "Dangerous curve to the left", "Dangerous curve to the right",
    "Double curve", "Bumpy road", "Slippery road", "Road narrows on the right",
    "Road work", "Traffic signals", "Pedestrians", "Children crossing",
    "Bicycles crossing", "Beware of ice/snow", "Wild animals crossing",
    "End of all speed and passing limits", "Turn right ahead", "Turn left ahead",
    "Ahead only", "Go straight or right", "Go straight or left", "Keep right",
    "Keep left", "Roundabout mandatory", "End of no passing",
    "End of no passing by vehicles > 3.5 tons"
]


# Title
st.title("🛑 Traffic Sign Classifier")

# Upload image
uploaded_file = st.file_uploader("Choose a traffic sign image...", type=["jpg", "png"])

if uploaded_file:
    image = Image.open(uploaded_file).convert("RGB")
    st.image(image, caption="Uploaded Image", use_column_width=True)

    # Preprocessing
    image = image.resize((48, 48))
    image = np.array(image) / 255.0
    image = np.transpose(image, (2, 0, 1))
    image = torch.tensor(image, dtype=torch.float).unsqueeze(0)

    # Inference
    with torch.no_grad():
        output = model(image)
        pred = output.argmax(1).item()

    st.success(f"Prediction: {sign_names[pred]}")