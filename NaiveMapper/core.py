import pickle
import sys
import traceback
from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.naive_bayes import BernoulliNB
from sklearn.utils.tests.test_linear_assignment import _hungarian

from CGRtools.files.RDFrw import RDFread, RDFwrite
from CGRtools.preparer import CGRcombo
from .DFS import get_map_dfs
from .bitstringen import Bitstringen
from .fragger import Fragger
# from .pairwise import Pairwise


def __chunk(iterable, n):
    """Yield successive n-sized chunks from 'iterable'."""
    for i in range(0, len(iterable), n):
        yield iterable[i:i + n]


def worker(file, debug=False):  # для души. увидим ошибки в RDF
    err, num = 0, 0
    for num, data in enumerate(file.read(), start=1):
        if debug or num % 10 == 1:
            # При условии debug выводит информацию о кажой 10-ой реакции, иначе о  каждой
            print("reaction: %d" % num, file=sys.stderr)
        try:
            yield data
        except Exception:
            err += 1
            print('reaction %d consist errors: %s' % (num, traceback.format_exc()), file=sys.stderr)

    print('%d from %d reactions processed' % (num - err, num), file=sys.stderr)


def getXY(reaction, fragger, pairwise, bitstring, chunk=None):
    sub_graph = nx.union_all(reaction['substrats'])  # Общий граф молекул реагента
    prod_graph = nx.union_all(reaction['products'])  # Общий граф молекул продукта
    sub_frag = fragger.get(sub_graph)  # Словарь фрагментов от данного атома реагента
    prod_frag = fragger.get(prod_graph)  # Словарь фрагментов от данного атома продукта

    # Генерирует список пар(атом_реагента,атом_продукта) и соответствующий ему список значений верного/неверного ААО
    pairs, y_bit = pairwise.get(sub_graph, prod_graph)

    # x-bit - битовую строку (молекулярный фингерпринт) для каждой пары атомов
    if chunk:
        for i in range(0, len(pairs), chunk):
            yield bitstring.get(sub_frag, prod_frag, pairs[i:i + chunk]), y_bit[i:i + chunk], pairs[i:i + chunk]
    else:
        x_bit = bitstring.get(sub_frag, prod_frag, pairs)
        yield x_bit, y_bit, pairs


def mapping(pairs, y, prod_graph, sub_graph):
    # opt_lh = 0  # переменная для подсчета среднего на атоме значения -log(вероятность_маппирования_атома)
    tmp = defaultdict(dict)  # создается кв.матрица (кол-во_атомов_реагента)Х(кол-во_атомов_продукта)
    for (s_atom, p_atom), proba in zip(pairs, y):
        tmp[s_atom][p_atom] = - proba[1]  # если данная пара атомов не сгенерирована ранее в pairs то значение None
    prob_matrix = pd.DataFrame(tmp).fillna(np.inf)  # заменяем значение None на +бесконечность (np.inf)

    # Вычисление решения Манкрес, который возвращает 2D массив - индексы для спариваний с наименьшей стоимостью.
    indexes = _hungarian(prob_matrix)

    p_reindex = prob_matrix.index.tolist()  # наименование строк, отвечающие за нумерацию атомов продукта
    s_reindex = prob_matrix.columns.values.tolist()  # наименование столбцов,отвечающие за нумерацию атомов реагента

    _m = {p_reindex[p]: s_reindex[s] for p, s in indexes}  # словарь со значениями атомного отображения
    # print("Munckris map: {}".format(_m))
    _map = get_map_dfs(sub_graph, prod_graph, _m, prob_matrix)
    # пересмотр решения Манкреса (поиск в глубину по графу продукта)
    # _map2 = get_map_dfsdb(sub_graph, prod_graph, _map, prob_matrix)
    '''for p, s in _map.items():
        opt_lh += prob_matrix.loc[p, s]
    opt_lh = opt_lh/len(_map)  # Подсчет среднего значения -log(вероятность_маппирования_атома)'''

    return _map  # , opt_lh , tmp


def truth(f_test, f_pred, ok, nok, er, debug=False):  # Проверка соответствия
    cgr = CGRcombo()
    with open(f_pred, encoding='cp1251') as predfile, open(f_test, encoding='cp1251') as testfile:
        # , open(kwargs['output_rank'], 'w') as f_txt:
        for i, (pred, test) in enumerate(zip(RDFread(predfile).read(), RDFread(testfile).read()), start=1):
            predHash = cgr.getCGR(pred).get_fear_hash()
            testHash = cgr.getCGR(test).get_fear_hash()
            # p_r = float(pred['meta']['Likelihood'])
            if predHash == testHash:
                ok += 1
                # s = str(i) + '\tcorrect\t' + str(p_r) + '\n'
            else:
                nok += 1
                # s = str(i) + '\tincorrect\t' + str(p_r) + '\n'
                er.append(i)
            # f_txt.write(s)

        print("Percentage\n\tO'k: %0.5f , \nNot O'k: %0.5f" % ((ok*100/(ok + nok)), (nok*100/(ok + nok))))
        if debug:
            print(len(er), '\n', er)

    return ok, nok

'''
if kwargs['stage'] == 1:  # стадия предсказания
    ok, nok = 0, 0
    er = []
    pairwise = Pairwise(0, 0)  # при предсказании, не применяем алгоритма Моргана для генерации пар сим./экв. атомов

    print("Testing set descriptor calculation")
    with open(kwargs['input'], encoding='cp1251') as fr, open(kwargs['output'], 'w') as fw:  # Открываю входящий и исходящие файлы
        outputdata = RDFwrite(fw)
        for reaction in worker(RDFread(fr)):  # берем по 1 реакции из входящего файла
            if kwargs['bitstring'] != 5:
                x, _, pairs = getXY(reaction)  # список пар атомов и соответствующие им битовые строки дескрипторов
                y = nb.predict_log_proba(x)  # на основании сгенерированного набора битовых строк дескрипторов
                # из обученой модели выводятся значения лагорифмов вероятностей проецирования (отображения) атомов
            else:
                sub_graph, prod_graph = nx.union_all(reaction['substrats']), nx.union_all(reaction['products'])
                sub_frag, prod_frag = fragger.get(sub_graph), fragger.get(prod_graph)
                pairs, _ = pairwise.get(sub_graph, prod_graph)
                y = list()
                for i in range((len(pairs)//200)+1):
                    if len(pairs)-(200*i):
                        # print(200*i, '-', 200*(i+1), '/', len(pairs))
                        x = bitstring.get(sub_frag, prod_frag, pairs[200*i:200*(i+1)])
                        y.extend([yy for yy in nb.predict_log_proba(x)])

            _map = mapping(pairs, y, nx.union_all(reaction['products']), nx.union_all(reaction['substrats']))
            tmp = []
            for graph in reaction['products']:
                tmp.append(nx.relabel_nodes(graph, _map, copy=True))
                # на основании обученной модели перемаппливаются атомы продукта
            reaction['products'] = tmp
            # reaction['meta']['Likelihood'] = opt_lh  # доп.графа в исх.файле, со ср.знач.вероятностей отображения

            """for s, p_lh in lh.items():
                lh_name = str(s) + '_ATOM_PROBABILITY_MAP'
                reaction['meta'][lh_name] = p_lh
                # доп.графы в исх.файле, с вероятностями отображения данного атома реагента на все атомы продукта
            """
            outputdata.write(reaction)  # запись реакции в исходящий файл
    _, _ = truth(kwargs['input'], kwargs['output'], ok, nok, er)  # Проверка соответствия

elif kwargs['stage'] == 2:  # стадия кросс-валидации
    indexes = list(range(c))  # генерации в список номеров(индексов) реакций
    # число разбиений на блоки тестового набора и кол-во повторений процедуры валидации
    folds, repeat = kwargs['folds'], kwargs['repeat']

    for r in range(repeat):  # Генерация повторения процедуры валидации
        print('Repeat ', r+1, '/', repeat)
        ok, nok = 0, 0
        errors = [[] for _ in range(folds)]
        # shuffle(indexes)  # перемешиваем индексы реакций
        pairwise = Pairwise(kwargs['pairs'], kwargs['duplicate'])

        for n in range(folds):  # генерация блоков(фолдов/разбиений) кросс-валидации
            print('Fold ', n+1, '/', folds)
            print("Training set descriptor calculation")
            file_1 = 'cross_v/mapping'+str(r)+str(n)+'.rdf'  # Контрольная выборка, для оценки предсказательной способности
            nb = BernoulliNB(alpha=1.0, binarize=None)  # Создаем новую модель Наивного Бейсовского классификатора

            with open(kwargs['input']) as fr, open(file_1, 'w') as fw:
                test_file = RDFwrite(fw)
                test = indexes[n::folds]  # для предсказания выбираются каждая N-ая реакция(из перемешенного списка)

                for num, reaction in enumerate(worker(RDFread(fr))):
                    if num in test:  # если номер рассматриваемой реакции совпал с номером тестового набора, то ...
                        # записываем её в файл для предсказания
                        test_file.write(reaction)
                    else:  # если номер рассматриваем реакции НЕ совпал с номером тестового набора, то ...
                        if kwargs['bitstring'] != 5:
                            x, y, _ = getXY(reaction)  # генерируем бит.строки дескрипторов(Х) и строку  ААО (Y)
                            nb.partial_fit(x, y, classes=pd.Series([False, True]))  # Обучение модели на основании Х и Y
                        else:
                            sub_graph, prod_graph = nx.union_all(reaction['substrats']), nx.union_all(reaction['products'])
                            sub_frag, prod_frag = fragger.get(sub_graph), fragger.get(prod_graph)
                            pairs, y = pairwise.get(sub_graph, prod_graph)

                            for i in range((len(pairs)//200)+1):
                                if len(pairs)-(200*i):
                                    # print(200*i, '-', 200*(i+1), '/', len(y))
                                    x = bitstring.get(sub_frag, prod_frag, pairs[200*i:200*(i+1)])
                                    nb.partial_fit(x, y[200*i:200*(i+1)], classes=pd.Series([False, True]))

            print("Testing set descriptor calculation")
            # при предсказании, алгоритм Моргана(для выделения групп сим./экв. атомов) не применяется
            pairwise = Pairwise(0, 0)
            file_2 = 'cross_v/output'+str(r)+str(n)+'.rdf'  # Контрольная выборка, с предсказанными ААО
            with open(file_1) as fr, open(file_2, 'w') as fw:
                output = RDFwrite(fw)
                for reaction in worker(RDFread(fr)):  # берем по 1 реакции из файла тестовго набора
                    if kwargs['bitstring'] != 5:
                        x, _, pairs = getXY(reaction)  # генерируем битовую строку дескрипторов и список пар атомов
                        y = nb.predict_log_proba(x)  # на основании сгенерированного набора битовых строк дескрипторов
                        # из модели выводятся значения лагорифмов вероятностей проецирования (отображения) атомов
                    else:
                        sub_graph, prod_graph = nx.union_all(reaction['substrats']), nx.union_all(reaction['products'])
                        sub_frag, prod_frag = fragger.get(sub_graph), fragger.get(prod_graph)
                        pairs, _ = pairwise.get(sub_graph, prod_graph)
                        y = list()
                        for i in range((len(pairs)//200)+1):
                            if len(pairs)-(200*i):
                                # print(200*i, '-', 200*(i+1), '/', len(pairs))
                                x = bitstring.get(sub_frag, prod_frag, pairs[200*i:200*(i+1)])
                                y.extend([yy for yy in nb.predict_log_proba(x)])

                    _map = mapping(pairs, y, nx.union_all(reaction['products']), nx.union_all(reaction['substrats']))
                    tmp = []
                    for graph in reaction['products']:
                        tmp.append(nx.relabel_nodes(graph, _map, copy=True))
                        # на основании обученной модели перемаппливаются атомы продукта
                    reaction['products'] = tmp
                    output.write(reaction)  # запись реакции в исходящий файл
            ok, nok = truth(file_1, file_2, ok, nok, errors[n])  # проверка предсказанных данных

else:
    print("Training set descriptor calculation")
    pairwise = Pairwise(kwargs['pairs'], kwargs['duplicate'])
    with open(kwargs['input']) as fr:
        for reaction in worker(RDFread(fr)):  # берем по 1 реакции из входящего файла
            if kwargs['bitstring'] != 5:
                x, y, _ = getXY(reaction)  # генерируем битовые строки дескрипторов(Х) и строку значений ААО(Y)
                nb.partial_fit(x, y, classes=pd.Series([False, True]))  # обучаем нашу модель на основании X и Y
            else:
                sub_graph, prod_graph = nx.union_all(reaction['substrats']), nx.union_all(reaction['products'])
                # Общие графы молекул реагента и продукта
                sub_frag, prod_frag = fragger.get(sub_graph), fragger.get(prod_graph)
                # Словари фрагментов для каждого атома реагента и каждого атома продукта
                pairs, y = pairwise.get(sub_graph, prod_graph)
                # Генерирует список пар и соответствующий ему список значений верного/неверного ААО

                for i in range((len(y)//200)+1):
                    if len(y)-(200*i):
                        # print(200*i, '-', 200*(i+1), '/', len(y))
                        x = bitstring.get(sub_frag, prod_frag, pairs[200*i:200*(i+1)])
                        nb.partial_fit(x, y[200*i:200*(i+1)], classes=pd.Series([False, True]))

    with open(kwargs['model'], 'wb') as train:
        pickle.dump(nb, train)  # записываем нашу обученную модель в файл
'''