#-*-coding:utf-8-*-
import pandas as pd
import numpy as np
import torch, os
from data_prepare import data_manager
from spo_dataset import NERCate, get_mask, collate_fn_ner_cate
from spo_model import SPOModel, NerLinkCateModel
from torch.utils.data import DataLoader, RandomSampler, TensorDataset
from tqdm import tqdm as tqdm
import torch.nn as nn
from utils import seed_torch, read_data, load_glove, calc_f1, get_threshold
from pytorch_pretrained_bert import BertTokenizer, BertAdam
from sklearn.model_selection import KFold, train_test_split
import logging

from sklearn.externals import joblib

file_name = 'TRAIN/Train_reviews.csv'
file_labels = 'TRAIN/Train_labels.csv'
sentences = data_manager.read_ner_cate(filename=file_name, filelabels=file_labels)
dev_X = []
test_data = pd.read_pickle('result/ner_link.pkl')
for index, row in test_data.iterrows():
    s = row['text']
    for item in row['result']:
        a = item[0]
        b = item[1]
        dev_X.append((s, a, b))
print(len(sentences),len(dev_X))
seed_torch(2019)
pred_vector = []
round = 0
name = 'cate'
if name =='polarity':
    id_label=4
    cate_list = data_manager.polarity
else:
    id_label=3
    cate_list = data_manager.category
# if round==0:
#     round+=1
#     continue
train_X = sentences
BERT_MODEL = 'bert-base-chinese'
CASED = False
t = BertTokenizer.from_pretrained(
    BERT_MODEL,
    do_lower_case=True,
    never_split=("[UNK]", "[SEP]", "[PAD]", "[CLS]", "[MASK]")
    #    cache_dir="~/.pytorch_pretrained_bert/bert-large-uncased-vocab.txt"
)

train_dataset = NERCate([['[CLS]'] + list(x[0]) + ['[CLS]'] for x in train_X], t,
                            pos1=[x[1] for x in train_X], pos2=[x[2] for x in train_X],
                            label=[x[id_label] for x in train_X], use_bert=True)
valid_dataset = NERCate([['[CLS]'] + list(x[0]) + ['[CLS]'] for x in dev_X], t,
                            pos1=[x[1] for x in dev_X], pos2=[x[2] for x in dev_X],
                            label=None, use_bert=True)
train_batch_size = 3
valid_batch_size = 3
model = NerLinkCateModel(vocab_size=None, init_embedding=None, encoder_size=128, dropout=0.2, num_outputs=len(cate_list), use_bert=True)
use_cuda=True
if use_cuda:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
else:
    device = torch.device("cpu")
model.to(device)
valid_dataloader = DataLoader(valid_dataset, collate_fn=collate_fn_ner_cate, shuffle=False, batch_size=valid_batch_size)

epochs = 2
t_total = int(epochs*len(train_X)/train_batch_size)
# optimizer = BertAdam([
#                 {'params': model.LSTM.parameters()},
#                 {'params': model.hidden.parameters()},
#                 {'params': model.classify.parameters()},
#                 {'params': model.span_extractor.parameters()},
#                 {'params': model.bert.parameters(), 'lr': 2e-5}
#             ],  lr=1e-3, warmup=0.05,t_total=t_total)
optimizer = torch.optim.Adam(model.parameters(), lr=2e-5)
clip = 50
loss_fn = nn.CrossEntropyLoss()
for epoch in range(epochs):
    print('round', round, 'epoch', epoch)
    model.train()
    train_loss = 0
    torch.cuda.manual_seed_all(epoch)
    train_dataloader = DataLoader(train_dataset, collate_fn=collate_fn_ner_cate, shuffle=True, batch_size=train_batch_size)
    for index, X, label, pos1, pos2, length in tqdm(train_dataloader):
        #model.zero_grad()
        X = nn.utils.rnn.pad_sequence(X, batch_first=True).type(torch.LongTensor)
        X = X.to(device)
        length = length.to(device)
        #mask_X = get_mask(X, length, is_cuda=use_cuda).to(device)
        pos1 = pos1.type(torch.LongTensor).to(device)
        pos2 = pos2.type(torch.LongTensor).to(device)
        label = label.to(device).type(torch.long)

        pred = model(X, pos1, pos2, length)
        loss = loss_fn(pred, label)
        loss.backward()

        #loss = loss_fn(pred, ner)
        optimizer.step()
        optimizer.zero_grad()
        # Clip gradients: gradients are modified in place
        # nn.utils.clip_grad_norm_(model.parameters(), clip)
        train_loss += loss.item()
    train_loss = train_loss/len(train_X)

model.eval()
valid_loss = 0
pred_set = []
for index, X, pos1, pos2, length in tqdm(valid_dataloader):
    X = nn.utils.rnn.pad_sequence(X, batch_first=True).type(torch.LongTensor)
    X = X.to(device)
    length = length.to(device)
    #mask_X = get_mask(X, length, is_cuda=use_cuda).to(device)
    pos1 = pos1.type(torch.LongTensor).to(device)
    pos2 = pos2.type(torch.LongTensor).to(device)
    with torch.no_grad():
        pred = model(X, pos1, pos2, length)
    pred_set.append(pred.cpu().numpy())

pred_set = np.concatenate(pred_set, axis=0)
top_class = np.argmax(pred_set, axis=1)
#INFO_THRE, thre_list = get_threshold(pred_set, label_set)
#print(INFO_THRE)
#torch.save(model.state_dict(), 'model_ner/ner_link_round %s' % round)
#pred_vector.append(pred_set)
#round += 1
# INFO = 'train loss %f, valid loss %f, acc %f, recall %f, f1 %f ' % (train_loss, valid_loss, INFO_THRE[0], INFO_THRE[1], INFO_THRE[2])
# logging.info(INFO)
# INFO = 'epoch %d, train loss %f, valid loss %f' % (epoch, train_loss, valid_loss)
# logging.info(INFO + '\t' + INFO_THRE)

result = pd.DataFrame()
result['text'] = [x[0] for x in dev_X]
result['pos1'] = [x[1] for x in dev_X]
result['pos2'] = [x[2] for x in dev_X]
result['predict_%s'%name] = [cate_list[x] for x in top_class]
result.to_pickle('result/final_%s.pkl'%name)
#pred_set
#pred_vector = np.concatenate(pred_vector, axis=0)
#np.save('result/gensim_vector_bert.npy', pred_vector)
    # 19 train loss　0.128424, val loss 0.153328, val_cos_loss 91155.319716

# 0.954
# 0.952,0.951,0.9495,0.946
# 0.9457,0.9517,0.95177 epoch==2 category drop cls

# polar
# 0.9668,0.960,0.9668
# #0.970,0.975 epoch==2 0.967 0.979