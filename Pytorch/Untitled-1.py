
import torch
import torch.nn as nn
import torch.nn.functional as F

# %%
class NeuralNetwork(nn.Module):
    
    def __init__(self, in_features = 4, h1=8, h2=9, out_features=3):
        super().__init__()
        
        self.fc1 = nn.Linear(in_features, h1)
        self.fc2 = nn.Linear(h1, h2)
        self.out = nn.Linear(h2, out_features)
        
    def forward(self, x):
        
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.out(x)
        
        return x
    
        
        
        

# %%
torch.manual_seed(42)

model = NeuralNetwork()

# %%
import numpy as np
import pandas as pd
import matplotlib as plt
# %matplotlib inline

# %%
url = 'https://gist.githubusercontent.com/curran/a08a1080b88344b0c8a7/raw/0e7a9b0a5d22642a06d3d5b9bcbad9890c8ee534/iris.csv'

df = pd.read_csv(url)

# %%
df

# %%
df['species'] = df['species'].replace('setosa', 0.0)
df['species'] = df['species'].replace('versicolor', 1.0)
df['species'] = df['species'].replace('virginica', 2.0)
df

# %%
df["species"].value_counts()

# %%
df = df.rename(columns={'species' : 'category'})

# %%
df

# %%
X = df.drop('category', axis = 1)
y = df['category']

# %%
X

# %%
y

# %% [markdown]
# #### convert X table to a np array through X.values

# %%
X = X.values
y = y.values

# %%
type(X)

# %%
from sklearn.model_selection import train_test_split

x_train, x_test, y_train, y_test = train_test_split(X, y, test_size=.2, random_state=42)

# %% [markdown]
# ##### Now we want to convert np arrays to tensors to work with torch

# %%
x_train = torch.FloatTensor(x_train)
x_test = torch.FloatTensor(x_test)

# %%
# y_train = torch.LongTensor(y_train)
# y_test = torch.LongTensor(y_test)

y_train = y_train.astype(np.int64)
y_test  = y_test.astype(np.int64)
y_train = torch.tensor(y_train, dtype=torch.long)
y_test  = torch.tensor(y_test,  dtype=torch.long)

# %%
criterion = nn.CrossEntropyLoss()

optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

# %%
epochs = 100
losses = []

for epoch in range(epochs):
    y_pred = model.forward(x_train)
    
    loss = criterion(y_pred, y_train)
    losses.append(loss.detach().numpy())
    
    # print loss every 10 epochs:
    
    if epoch % 10 == 0:
        print(f"Epoch num: {epoch}, Loss equals: {loss}")
        
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    

# %%
with torch.no_grad():
    y_eval = model.forward(x_test)
    loss = criterion(y_eval, y_test)

# %%
loss

# %%
correct = 0


with torch.no_grad():
    for i, data in enumerate(x_test):
        y_val = model.forward(data)
        
        print(f"{i+1}--> {str(y_val)} \t {y_test[i]} \t {y_val.argmax().item()}")
        
        if y_val.argmax().item() == y_test[i]:
            correct+=1
        
    print(f"there are {correct} correct!")    

# %%

new_iris = torch.tensor([5.9, 3.0, 5.1, 1.8])

with torch.no_grad():
    print(model(new_iris))

