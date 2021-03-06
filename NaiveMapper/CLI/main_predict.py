from pprint import pprint
from timeit import default_timer as timer
from keras.models import load_model
from keras import backend as kb
from random import shuffle
import networkx as nx
import numpy as np
import pickle

from CGRtools.files.RDFrw import RDFread, RDFwrite
from ..bitstringen import Bitstringen
from ..core import getXY, mapping, truth, worker
from ..fragger import Fragger
from ..pairwise import Pairwise


kb.set_session(kb.tf.Session(config=kb.tf.ConfigProto(inter_op_parallelism_threads=2, intra_op_parallelism_threads=2)))


def remap(graphs, maps):
    tmp = []
    for graph in graphs:
        tmp.append(graph.remap({k: v for k, v in maps.items() if k in graph}, copy=True))
    return tmp


def predict_core(**kwargs):
    # Загружаем уже существующую модель
    model = pickle.load(kwargs['model'])
    fragger = Fragger(f_type=model['fragment_type'], _min=model['min'], _max=model['max'], _deep=model['deep'],
                      _min2=model['min2'], _max2=model['max2'], _fuzzy=model['fuzzy'])
    bitstring = Bitstringen(model['bitstring'], model['length'], model['fragment_count'])
    # При предсказании, НИКОГДА не применяем алгоритма Моргана для генерации пар сим./экв. атомов
    pairwise = Pairwise(0, False)

    print("Testing set descriptor calculation")
    if model['type_model'] == 'keras':
        mod_1 = load_model(model['model_filename'])
    with open(kwargs['input'], encoding='cp1251') as fr, open(kwargs['output'], 'w') as fw:
        outputdata = RDFwrite(fw)

        for reaction in worker(RDFread(fr), kwargs['debug']):
            p_graph = nx.union_all(reaction['products'])
            p_nodes = [k + max(p_graph.nodes()) for k in p_graph.nodes()]
            shuffle(p_nodes)
            reaction.products._MindfulList__data = remap(reaction['products'],
                                                         {k: v for k, v in zip(p_graph.nodes(), p_nodes)})
            y, pairs = [], []
            for x, _, drop_pairs in getXY(reaction, fragger, pairwise, bitstring, model['chunk']):
                '''
                На основании сгенерированного набора битовых строк дескрипторов из обученой модели 
                выводятся значения логорифмов вероятностей проецирования (отображения) атомов
                '''
                pairs.extend(drop_pairs)
                if model['type_model'] == 'keras':
                    yi = mod_1.predict(x.values)
                    y.extend(np.log(np.where(yi > 0, yi, 1e-20)))
                else:
                    y.extend(model['model'].predict_log_proba(x))

            _map = mapping(pairs, y, nx.union_all(reaction['products']), nx.union_all(reaction['substrats']))

            # на основании обученной модели перемаппливаются атомы продукта
            reaction.products._MindfulList__data = remap(reaction['products'], _map)
            outputdata.write(reaction)  # запись реакции в исходящий файл

    _, _ = truth(kwargs['input'], kwargs['output'], 0, 0, [], kwargs['debug'])  # Проверка соответствия
