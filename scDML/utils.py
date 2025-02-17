#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Dec 21 05:00:07 2021
@author: xiaokangyu
"""
import numpy as np
import pandas as pd
import scanpy as sc
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.pyplot import rc_context
import torch
import random
import os
from anndata import AnnData
import seaborn as sns 
import math 
from IPython.display import display
import plotly 
import plotly.graph_objects as go
from sklearn.metrics.cluster import adjusted_rand_score,normalized_mutual_info_score

##### Find optimal resolution given ncluster #####
def find_resolution(adata_, n_clusters, random):
    adata = adata_.copy()
    obtained_clusters = -1
    iteration = 0
    resolutions = [0., 1000.]
    while obtained_clusters != n_clusters and iteration < 50:
        current_res = sum(resolutions)/2
        sc.tl.louvain(adata, resolution = current_res, random_state = random)
        labels = adata.obs['louvain']
        obtained_clusters = len(np.unique(labels))

        if obtained_clusters < n_clusters:
            resolutions[0] = current_res
        else:
            resolutions[1] = current_res
        iteration = iteration + 1
    return current_res

##### calculate ARI and NMI #####
def calulate_ari_nmi(adata_integrated,n_cluster=4):
    sc.pp.neighbors(adata_integrated,random_state=0)
    reso=find_resolution(adata_integrated,n_cluster,0)
    sc.tl.louvain(adata_integrated,reso,random_state=0)
    sc.tl.umap(adata_integrated)
    if(adata_integrated.X.shape[1]==2):
        adata_integrated.obsm["X_emb"]=adata_integrated.X
    ARI= adjusted_rand_score(adata_integrated.obs["celltype"].astype(str), adata_integrated.obs["louvain"])
    NMI= normalized_mutual_info_score(adata_integrated.obs["celltype"].astype(str), adata_integrated.obs["louvain"])
    print("louvain clustering result(resolution={}):n_cluster={}".format(reso,n_cluster))
    print("ARI:",ARI)
    print("NMI:",NMI)
    return ARI,NMI


###### print dataset information ######
def print_dataset_information(adata,batch_key="BATCH",celltype_key="celltype"):
    if batch_key is not None and batch_key not in adata.obs.columns:
        print('Please check whether there is a {} column in adata.obs to identify batch information!'.format(batch_key))
        raise IOError

    if celltype_key is not None and batch_key not in adata.obs.columns:
        print('Please check whether there is a {} column in adata.obs to identify celltype information!'.format(celltype_key))
        raise IOError
    
    print("===========print brief infomation of dataset ===============")
    print("===========there are {} batchs in this dataset==============".format(len(adata.obs[batch_key].value_counts())))
    print("===========there are {} celltypes with this dataset=========".format(len(adata.obs[celltype_key].value_counts())))
    data_info=pd.crosstab(adata.obs[batch_key],adata.obs[celltype_key],margins=True,margins_name="Total")
    display(data_info)

##### check whether input is suitable for scDML preprocessing #####
def checkInput(adata,batch_key,preprocessed):
    if(preprocessed):        
        if("init_cluster" not in adata.obs.columns):
            print("scDML can't find normalized data in adata.layers,the preprocessed data matrix should be stored in adata.layers[\"normalized_input\"]")
            raise IOError
        if("X_pca" not in adata.obsm.keys()):
            raise IOError

    if not isinstance(adata,AnnData):
        print("adata is not an object of AnnData,please convert Input data to Anndata")
        raise IOError
    
    if batch_key is not None and batch_key not in adata.obs.columns:
        print('Please check whether there is a {} column in adata.obs to identify batch information!'.format(batch_key))
        raise IOError
    elif batch_key is None:
        print("scDML cretate \"BATCH\" column to set all cell to one batch!!!")
        batch_key="BATCH"
        adata.obs[batch_key]="1" 
    
    if(adata.obs[batch_key].dtype.name != "categroy"):
        adata.obs[batch_key]=adata.obs[batch_key].astype("category")
    return batch_key

##### set random seed for reproduce result ##### 
def seed_torch(seed=1029):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed) # if you are using multi-GPU.
    torch.backends.cudnn.badatahmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.enabled = False

##### find threshold with merge_rule1 #####
def find_threshold(n_clusters,cor_mat):
    cor=cor_mat.copy()
    iteration = 0
    threhold = [0., 20.]
    obtained_clusters = -1
    
    while obtained_clusters != n_clusters and iteration < 50:
        current_thre = sum(threhold)/2
        #print("threshold={}".format(current_thre))
        G=nx.Graph()
        near_cluster=dict()
        cluster_set=set()
        for i in range(cor.shape[0]):
            near_cluster[i]=i
        for i in range(len(cor)):
            for j in range(i+1,len(cor)):
                if(cor.values[i,j]>=current_thre):
                    if(cor.values[j,i]>cor.values[j,near_cluster[j]]):
                        near_cluster[j]=i

        for i in near_cluster.keys():
            cluster_set.add((i,near_cluster[i]))
            cluster_set.add((near_cluster[i],i))

        edge_set=cluster_set.copy()
        G.add_edges_from(edge_set)
        obtained_clusters=nx.number_connected_components(G)
        if obtained_clusters < n_clusters:
            threhold[0] = current_thre
        else:
            threhold[1] = current_thre
        iteration = iteration + 1
    print("=================when ncluster={},threhold={}=====".format(n_clusters,current_thre))
    return current_thre

##### type of merging cluster(apply min distance similar to hierarchical clustering) #####
def merge_rule1(cor,num_init_cluster,n_cluster=None,threshold=None,save_dir=None):
    """
    """
    print("merge_rule1.....")
    if(n_cluster is None and threshold is None):
        print("please provide a fixed threshold or a fixed n_cluster")
        raise IOError
    if(n_cluster is None): # suppose if don't provide n_cluster, the threshold muse be provided
        cluster_set=set()
        near_cluster=dict()
        for i in range(num_init_cluster):
            near_cluster[i]=i
        for i in range(len(cor)):
            for j in range(i+1,len(cor)):
                if(cor.values[i,j]>=threshold):## 
                    if(cor.values[j,i]>cor.values[j,near_cluster[j]]):
                        near_cluster[j]=i
        for i in near_cluster.keys():
            cluster_set.add((i,near_cluster[i]))
            cluster_set.add((near_cluster[i],i))
        G=nx.Graph()
        edge_set=cluster_set.copy()
        G.add_edges_from(edge_set)
        map_set=list(nx.connected_components(G)) 
        return map_set
    else:
        threshold=find_threshold(n_cluster,cor)
        cluster_set=set()
        near_cluster=dict()
        for i in range(num_init_cluster):
            near_cluster[i]=i
    
        for i in range(len(cor)):
            for j in range(i+1,len(cor)):
                if(cor.values[i,j]>=threshold):## 
                    if(cor.values[j,i]>cor.values[j,near_cluster[j]]):
                        near_cluster[j]=i
        for i in near_cluster.keys():
            cluster_set.add((i,near_cluster[i]))
            cluster_set.add((near_cluster[i],i))
        G=nx.Graph()
        edge_set=cluster_set.copy()
        G.add_edges_from(edge_set)
        map_set=list(nx.connected_components(G)) 
        return map_set

##### type of merging cluster(apply mean distance similar to hierarchical clustering) #####
def merge_rule2(sim_matrix,NN_pair,cluster_size,n_cluster=None,verbose=True,threshold=None):
    """
    sim_matrix:initization for merge
    NN-pair:calculate new cosine
    cluster_size---record cluster number size
    n_cluster--- merge number of cluster
    map_set=connected_cluster2(sim_matrix.copy(),NN_pair.copy(),cluster_size.copy(),n_cluster=3)
    """
    if(threshold is None):
        if(verbose):
            print("merge_rule2(set ncluster={}).....".format(n_cluster))
        if(type(list(sim_matrix.columns)[0])!=str):
            temp_col_names=list(sim_matrix.columns)
            sim_matrix.columns=[str(i) for i in temp_col_names]
        sim_matrix.columns="cluster_"+sim_matrix.columns
        sim_matrix.index=list(sim_matrix.columns)
        
        NN_pair.columns=sim_matrix.columns
        NN_pair.index=list(sim_matrix.columns)
        
        cluster_size=pd.DataFrame(cluster_size)
        cluster_size.columns=["init_cluster_num"]
        cluster_size.index=list(sim_matrix.columns)##convert to dataframe
        
        NN_pair_mat=NN_pair.values
        num_clu=len(cluster_size)
        cnt=0
        max_clu=num_clu
        map_dict={}
        for i in list(sim_matrix.index):
            map_dict[i]=None
        df=sim_matrix.copy()
        while(df.shape[1]>n_cluster):
            max_sim = -math.inf 
            for i in list(df.index):  
                for j in list(df.columns):
                    cnt=cnt+1
                    val=df.loc[i,j]
                    if val > max_sim:
                        max_sim = val
                        closest_part = (i, j)

            # delete two merged cluster
            del_cluster=list(closest_part)
            df =df.drop(labels=del_cluster)  
            df =df.drop(labels=del_cluster,axis=1) 
            ind=list(df.index)
            ## add new cluster(cluster_size)
            new_cluster_name="cluster_"+str(max_clu)
            #print(str(closest_part)+" merged to {}".format(new_cluster_name))
            map_dict[new_cluster_name]=list(closest_part)
            cluster_size.loc[new_cluster_name]=cluster_size.loc[closest_part[0],"init_cluster_num"]+cluster_size.loc[closest_part[1],"init_cluster_num"]
            #print(cluster_size)
            NN_pair.loc[new_cluster_name] =NN_pair.loc[closest_part[0]].values +NN_pair.loc[closest_part[1]].values
            row_val=np.append(NN_pair.loc[new_cluster_name].values,0)
            NN_pair[new_cluster_name]=row_val
            if(df.empty):# when ncluster=1,df is empy
                max_clu=max_clu+1
                df=pd.DataFrame(np.array([[1]]),index=[new_cluster_name],columns=[new_cluster_name])
            else:
                df.loc[new_cluster_name] = -1
                for col in df.columns:
                    min_size=min(cluster_size.loc[new_cluster_name,"init_cluster_num"],cluster_size.loc[col,"init_cluster_num"])
                    df.loc[new_cluster_name,col]=NN_pair.loc[new_cluster_name,col]/min_size

                row_val=np.append(df.loc[new_cluster_name].values,0)
                df[new_cluster_name]=row_val
                max_clu=max_clu+1
        # define recurve function to find cluster connection
        def leaf_traversal(node,s):
            if map_dict[node] is None:
                #s.add(node)
                s.add(int(node.split("_")[1]))
            else:
                if map_dict[node][0] is not None:
                    leaf_traversal(map_dict[node][0], s)
                if map_dict[node][1] is not None:
                    leaf_traversal(map_dict[node][1], s)
        
        final_merged=list(df.columns)
        final_conected=[set() for _ in range(len(final_merged))]
        for i in range(len(final_merged)):
            leaf_traversal(final_merged[i],final_conected[i])
        map_set=final_conected.copy()
        return map_set
    else:
        print("thresold is set to {}".format(threshold))
        if(type(list(sim_matrix.columns)[0])!=str):
            temp_col_names=list(sim_matrix.columns)
            sim_matrix.columns=[str(i) for i in temp_col_names]
        sim_matrix.columns="cluster_"+sim_matrix.columns
        sim_matrix.index=list(sim_matrix.columns)
        
        NN_pair.columns=sim_matrix.columns
        NN_pair.index=list(sim_matrix.columns)
        
        cluster_size=pd.DataFrame(cluster_size)
        cluster_size.columns=["init_cluster_num"]
        cluster_size.index=list(sim_matrix.columns)##convert to dataframe
        
        NN_pair_mat=NN_pair.values
        num_clu=len(cluster_size)
        cnt=0
        max_clu=num_clu
        map_dict={}
        for i in list(sim_matrix.index):
            map_dict[i]=None
        df=sim_matrix.copy()
        while(max(df.max())>= threshold ):
            max_sim = -math.inf 
            for i in list(df.index):  
                for j in list(df.columns):
                    cnt=cnt+1
                    val=df.loc[i,j]
                    if val > max_sim:
                        max_sim = val
                        closest_part = (i, j)

            # delete two merged cluster
            del_cluster=list(closest_part)
            df =df.drop(labels=del_cluster)  
            df =df.drop(labels=del_cluster,axis=1) 
            ind=list(df.index)
            ## add new cluster(cluster_size)
            new_cluster_name="cluster_"+str(max_clu)
            #print(str(closest_part)+" merged to {}".format(new_cluster_name))
            map_dict[new_cluster_name]=list(closest_part)
            cluster_size.loc[new_cluster_name]=cluster_size.loc[closest_part[0],"init_cluster_num"]+cluster_size.loc[closest_part[1],"init_cluster_num"]
            #print(cluster_size)
            NN_pair.loc[new_cluster_name] =NN_pair.loc[closest_part[0]].values +NN_pair.loc[closest_part[1]].values
            row_val=np.append(NN_pair.loc[new_cluster_name].values,0)
            NN_pair[new_cluster_name]=row_val
            if(df.empty):# when ncluster=1,df is empy
                #print("df is empty...")
                max_clu=max_clu+1
                df=pd.DataFrame(np.array([[1]]),index=[new_cluster_name],columns=[new_cluster_name])
            else:
                df.loc[new_cluster_name] = -1
                for col in df.columns:
                    min_size=min(cluster_size.loc[new_cluster_name,"init_cluster_num"],cluster_size.loc[col,"init_cluster_num"])
                    df.loc[new_cluster_name,col]=NN_pair.loc[new_cluster_name,col]/min_size

                row_val=np.append(df.loc[new_cluster_name].values,0)
                df[new_cluster_name]=row_val
                max_clu=max_clu+1
        # define recurve function to find cluster connection
        def leaf_traversal(node,s):
            if map_dict[node] is None:
                #s.add(node)
                s.add(int(node.split("_")[1]))
            else:
                if map_dict[node][0] is not None:
                    leaf_traversal(map_dict[node][0], s)
                if map_dict[node][1] is not None:
                    leaf_traversal(map_dict[node][1], s)
        final_merged=list(df.columns)
        final_conected=[set() for _ in range(len(final_merged))]
        for i in range(len(final_merged)):
            leaf_traversal(final_merged[i],final_conected[i])

        map_set=final_conected.copy()
        return map_set

##### calculate similarity matrix of cluster with KNN and MNN #####
def cal_sim_matrix(knn_in_batch,mnn_out_batch,cluster_label,verbose):
    """
    calculate similarity matrix of cluster with KNN and MNN
    
    Argument:
    ------------------------------------------------------------------
    - knn_in_batch: 'ndarray(N1*2)', knn pair found in PCA embedding space
    - mnn_out_batch: 'ndarray(N2*2)', mnn pair found in PCA embedding space
    - verbose,`bool`, print additional information
    ------------------------------------------------------------------
    """
    cluster_set=range(len(np.unique(cluster_label)))
    mnn_inbatch_df=pd.DataFrame({"pair1_clust":cluster_label[knn_in_batch[:,0]].astype(int),
                           "pair2_clust":cluster_label[knn_in_batch[:,1]].astype(int),
                           "pair1":knn_in_batch[:,0],
                           "pair2":knn_in_batch[:,1]})
    knn_summary=pd.crosstab(mnn_inbatch_df.pair1_clust,mnn_inbatch_df.pair2_clust)

    knn_table=pd.DataFrame(0, index=cluster_set, columns=cluster_set)
    for ind in list(knn_summary.index):
        for col in list(knn_summary.columns):
            knn_table.loc[ind,col]=knn_summary.loc[ind,col]
    if(verbose):
        print("delete inner edge which link same cluster")
    np.fill_diagonal(knn_table.values,0)
    if(verbose):
        print("{} knn pair in batch link different cluster".format(np.sum(knn_table.values)))

    if(len(mnn_out_batch)==0): # no mnn pair
        mnn_summary=pd.DataFrame(0, index=cluster_set, columns=cluster_set)
    else: # have mnn pair
        mnn_bwbatch_df=pd.DataFrame({"pair1_clust":cluster_label[mnn_out_batch[:,0]].astype(int),
                            "pair2_clust":cluster_label[mnn_out_batch[:,1]].astype(int),
                            "pair1":mnn_out_batch[:,0],
                            "pair2":mnn_out_batch[:,1]})
        mnn_summary=pd.crosstab(mnn_bwbatch_df.pair1_clust,mnn_bwbatch_df.pair2_clust)
    mnn_table=pd.DataFrame(0, index=cluster_set, columns=cluster_set)
    for ind in list(mnn_summary.index):
        for col in list(mnn_summary.columns):
            mnn_table.loc[ind,col]=mnn_summary.loc[ind,col]
    if(verbose):
        print("delete inner edge which link same cluster")
    np.fill_diagonal(mnn_table.values,0)
    if(verbose):
        print("{} mnn pair in batch link different cluster".format(np.sum(mnn_table.values)))
    print("===================================================================================") 
    print("NN pair ratio(number of MNN pairs/number of KNN pairs)={}".format(np.sum(mnn_table.values)/np.sum(knn_table.values)))
    print("===================================================================================") 
    ## calucate link conectivity between cluster
    sum_matrix=knn_table.values+mnn_table.values
    link_nn=knn_table + mnn_table
    mnn_cor=np.zeros_like(sum_matrix,dtype=float)
    clu_size=np.array(cluster_label.value_counts()) 
    for i in range(len(mnn_cor)):
        for j in range(len(mnn_cor)):
            mnn_cor[i,j]=sum_matrix[i,j].astype(float)/min(clu_size[i],clu_size[j])

    cor=pd.DataFrame(data=mnn_cor)
    cor_mat=cor.values
    np.fill_diagonal(cor_mat, -1)    
    return cor,link_nn

##### plot connection point(KNN or MNN)
def connectpoints_mnn(x,y,p1,p2,flag="in"):# 
    x1, x2 = x[p1], x[p2]
    y1, y2 = y[p1], y[p2]
    if(flag=="in"):
        plt.plot([x1,x2],[y1,y2],"-",linewidth=0.5,color="black",alpha=0.03)
    else :
        plt.plot([x1,x2],[y1,y2],"-",linewidth=0.5,color="pink",alpha=0.03)
##### plot connection point(KNN or MNN)      
def plotNNpair(X_umap,nnset,batch,flag="in",save_dir=None):
    plt.figure(figsize=(10,8))#
    for label in np.unique(batch):
        plt.scatter(X_umap[label==batch,0],X_umap[label==batch,1],label=label,s=2)
    for i in range(len(nnset)):
        x=[X_umap[nnset[i,0],0],X_umap[nnset[i,1],0]]
        y=[X_umap[nnset[i,0],1],X_umap[nnset[i,1],1]]
        connectpoints_mnn(x,y,0,1,flag=flag)
    legend = plt.legend(loc="upper left", title='BATCH', shadow=True, fontsize='x-large',markerscale=5.0)
    if(flag=="in"):
        plt.title("KNN pair connection intra batch")
        plt.savefig(save_dir+"/knn_connection_intra_batch.png")
    else:
        plt.title("MNN pair connection between batch")
        plt.savefig(save_dir+"/mnn_connection_inter_batch.png")

#######plot HeatMap with similarity calculated by scDML ######
def plotHeatMap(cor,Z=None):
    #sns.set(font_scale=1.0)
    np.fill_diagonal(cor.values,max(cor.max()))
    cp=sns.clustermap(cor/max(cor.max()),cmap='Reds',col_linkage=Z,row_linkage=Z,yticklabels=False,xticklabels=False)
    cp.ax_row_dendrogram.set_visible(False)
    return cp

##### plot Dendrogram tree plot #####
def plotDendrogram(sim_matrix,NN_pair,cluster_size):
    """
    """
    Z=[]
    if(type(list(sim_matrix.columns)[0])!=str):
        temp_col_names=list(sim_matrix.columns)
        sim_matrix.columns=[str(i) for i in temp_col_names]
    sim_matrix.columns="cluster_"+sim_matrix.columns
    sim_matrix.index=list(sim_matrix.columns)
    
    NN_pair.columns=sim_matrix.columns
    NN_pair.index=list(sim_matrix.columns)
    
    cluster_size=pd.DataFrame(cluster_size)
    cluster_size.columns=["init_cluster_num"]
    cluster_size.index=list(sim_matrix.columns)##convert to dataframe
    
    NN_pair_mat=NN_pair.values
    num_clu=len(cluster_size)
    cnt=0
    temp_sim=0.0
    max_clu=num_clu
    map_dict={}
    for i in list(sim_matrix.index):
        map_dict[i]=None
     
    MAX_VAL=max(sim_matrix.max())
    df=sim_matrix.copy()

    # define recurve function to find cluster connection
    def leaf_traversal(node,s):
        if map_dict[node] is None:
            #s.add(node)
            s.add(int(node.split("_")[1]))
        else:
            if map_dict[node][0] is not None:
                leaf_traversal(map_dict[node][0], s)
            if map_dict[node][1] is not None:
                leaf_traversal(map_dict[node][1], s)

    while(df.shape[1]>1):
        max_sim = -math.inf 
        for i in list(df.index):  
            for j in list(df.columns):
                cnt=cnt+1
                val=df.loc[i,j]
                if val > max_sim:
                    max_sim = val
                    closest_part = (i, j)

        # delete two merged cluster
        del_cluster=list(closest_part)
        df =df.drop(labels=del_cluster)  
        df =df.drop(labels=del_cluster,axis=1) 
        ind=list(df.index)
        new_cluster_name="cluster_"+str(max_clu)
        map_dict[new_cluster_name]=list(closest_part)
        cluster_size.loc[new_cluster_name]=cluster_size.loc[closest_part[0],"init_cluster_num"]+cluster_size.loc[closest_part[1],"init_cluster_num"]
        #print(cluster_size)
        NN_pair.loc[new_cluster_name] =NN_pair.loc[closest_part[0]].values +NN_pair.loc[closest_part[1]].values
        row_val=np.append(NN_pair.loc[new_cluster_name].values,0)
        NN_pair[new_cluster_name]=row_val
        
        if(df.empty):# when ncluster=1,df is empy
            max_clu=max_clu+1
            df=pd.DataFrame(np.array([[1]]),index=[new_cluster_name],columns=[new_cluster_name])
        else:
            df.loc[new_cluster_name] = -1
            for col in df.columns:
                min_size=min(cluster_size.loc[new_cluster_name,"init_cluster_num"],cluster_size.loc[col,"init_cluster_num"])
                df.loc[new_cluster_name,col]=NN_pair.loc[new_cluster_name,col]/min_size

            row_val=np.append(df.loc[new_cluster_name].values,0)
            df[new_cluster_name]=row_val
            max_clu=max_clu+1
        s1=set()
        s2=set()
        temp_sim=temp_sim+max_sim/MAX_VAL
        leaf_traversal(closest_part[0],s1)
        leaf_traversal(closest_part[1],s2)
        num_node=len(s1)+len(s2)
        Z.append([int(closest_part[0].split("_")[1]),int(closest_part[1].split("_")[1]),temp_sim,num_node])
    final_merged=list(df.columns)
    final_conected=[set() for _ in range(len(final_merged))]
    for i in range(len(final_merged)):
        leaf_traversal(final_merged[i],final_conected[i])

    map_set=final_conected.copy()
    return Z        

####### plot sanky diagram #####     
def plotSankey(df,cat_cols=[],value_cols='',title='Sankey Diagram'):
    colorPalette=sns.color_palette('Blues',20).as_hex()
    labelList = []
    colorNumList = []
    for catCol in cat_cols:
        labelListTemp =  list(set(df[catCol].values))
        colorNumList.append(len(labelListTemp))
        labelList = labelList + labelListTemp
    labelList = list(dict.fromkeys(labelList))
    colorList = []
    for idx, colorNum in enumerate(colorNumList):
        colorList = colorList + [colorPalette[idx]]*colorNum
    # transform df into a source-target pair
    for i in range(len(cat_cols)-1):
        if i==0:
            sourceTargetDf = df[[cat_cols[i],cat_cols[i+1],value_cols]]
            sourceTargetDf.columns = ['source','target','count']
        else:
            tempDf = df[[cat_cols[i],cat_cols[i+1],value_cols]]
            tempDf.columns = ['source','target','count']
            sourceTargetDf = pd.concat([sourceTargetDf,tempDf])
        sourceTargetDf = sourceTargetDf.groupby(['source','target']).agg({'count':'sum'}).reset_index()
        
    # add index for source-target pair
    sourceTargetDf['sourceID'] = sourceTargetDf['source'].apply(lambda x: labelList.index(x))
    sourceTargetDf['targetID'] = sourceTargetDf['target'].apply(lambda x: labelList.index(x))
    # creating the sankey diagram
    data = dict(type='sankey',
        node = dict(pad = 10,thickness = 20,line = dict(color = "black",width = 0.5),label = labelList),
        link = dict(source = sourceTargetDf['sourceID'],target = sourceTargetDf['targetID'],value = sourceTargetDf['count'])
      )
    layout =  dict(title = title,font = dict(size = 10))
    fig = dict(data=[data], layout=layout)
    fig=go.Figure(data=data,layout=layout)
    for x_coordinate, column_name in enumerate(cat_cols):
        fig.add_annotation(
            x=x_coordinate / (len(cat_cols) - 1),
            y=1.1,
            xref="paper",
            yref="paper",
            text=column_name,
            showarrow=False,
            font=dict(size=15),
            align="center",
            )
    return fig

##### plot embedding #####
def visulize_encode(X,cluster_group,true_group,batch,epoch=-1,save_dir=None,save_embedding=False,flag="Full"):
    if(X.shape[1]==2):# if embedding is 2D dimension
        sc_data=sc.AnnData(X)
        sc_data.obs["cluster_celltype"]=cluster_group.astype(str);
        sc_data.obs["true_celltype"]=true_group.astype(str)
        sc_data.obs["batch"]=batch.astype(str);
        sc_data.obsm["X_proj"]=X
        fig, axs = plt.subplots(1, 3, figsize=(30,8),constrained_layout=True)
        sc.pl.embedding(sc_data,basis="proj",color=["cluster_celltype"],size=50,legend_fontsize=20,show=False,ax=axs[0])
        axs[0].patch.set_alpha(1)
        axs[0].set_title('scDML cluster', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[0].set_xlabel(xlabel="X1",fontsize=25)
        axs[0].set_ylabel(ylabel="X2",fontsize=25)
        
        sc.pl.embedding(sc_data,basis="proj",color=["batch"],size=50,show=False,legend_fontsize=20,ax=axs[1])
        axs[1].patch.set_alpha(1)
        axs[1].set_title('BATCH', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[1].set_xlabel(xlabel="X1",fontsize=25)
        axs[1].set_ylabel(ylabel="X2",fontsize=25)
    
        sc.pl.embedding(sc_data,basis="proj",color=["true_celltype"],size=50,show=False,legend_fontsize=20,ax=axs[2])
        axs[2].patch.set_alpha(1)
        axs[2].set_title('true celltype', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[2].set_xlabel(xlabel="X1",fontsize=25)
        axs[2].set_ylabel(ylabel="X2",fontsize=25)
        plt.savefig(save_dir+"/scDML_epoch_{}".format(epoch)+"_proj.png")
        plt.show()
    else:    
        sc_data=sc.AnnData(X)
        sc_data.obs["cluster_celltype"]=cluster_group.astype(str);
        sc_data.obs["true_celltype"]=true_group.astype(str)
        sc_data.obs["batch"]=batch.astype(str);
        sc.pp.neighbors(sc_data,random_state=0)
        sc.tl.umap(sc_data)
        fig, axs = plt.subplots(1, 3, figsize=(30,8),constrained_layout=True)
        sc.pl.umap(sc_data,color=["cluster_celltype"],size=50,legend_fontsize=20,show=False,ax=axs[0])
        axs[0].patch.set_alpha(1)
        axs[0].set_title('scDML cluster', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[0].set_xlabel(xlabel="UMAP1",fontsize=25)
        axs[0].set_ylabel(ylabel="UMAP2",fontsize=25)
        
        sc.pl.umap(sc_data,color=["batch"],size=50,show=False,legend_fontsize=20,ax=axs[1])
        axs[1].patch.set_alpha(1)
        axs[1].set_title('BATCH', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[1].set_xlabel(xlabel="UMAP1",fontsize=25)
        axs[1].set_ylabel(ylabel="UMAP2",fontsize=25)
    
        sc.pl.umap(sc_data,color=["true_celltype"],size=50,show=False,legend_fontsize=20,ax=axs[2])
        axs[2].patch.set_alpha(1)
        axs[2].set_title('true celltype', fontdict={'fontsize': 25, 'fontweight': 'medium'})
        axs[2].set_xlabel(xlabel="UMAP1",fontsize=25)
        axs[2].set_ylabel(ylabel="UMAP2",fontsize=25)
        if(flag=="Full"):
            plt.savefig(save_dir+"/scDML_epoch_{}".format(epoch)+"_Full_dataset.png")
        else:
            plt.savefig(save_dir+"/scDML_epoch_{}".format(epoch)+"_Sample_dataset.png")
        plt.show()   
    if(save_embedding):
        scDML_corrected=sc.AnnData(X)
        scDML_corrected.obs["celltype"]=true_group.astype(str)
        scDML_corrected.obs["BATCH"]=batch.astype(str)
        scDML_corrected.obsm["X_emb"]=scDML_corrected.X
        scDML_corrected.write(save_dir+"/scDML_epoch_{}_corrected.h5ad".format(epoch))
 



