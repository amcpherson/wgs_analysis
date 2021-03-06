import os
import seaborn
import lda
import scipy.stats
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import pkg_resources


def reverse_complement(sequence):
    return sequence[::-1].translate(str.maketrans('ACTGactg','TGACtgac'))


def fit_sample_signatures(snvs_table, sig_prob, subset_col):

    # Filter samples with fewer than 100 SNVs
    snv_counts = snvs_table.groupby(subset_col).size()
    snvs_table = snvs_table.set_index(subset_col).loc[snv_counts[snv_counts > 100].index].reset_index()

    tri_nuc_table = (snvs_table.groupby([subset_col, 'tri_nuc_idx'])
        .size().unstack().fillna(0).astype(int))

    if len(tri_nuc_table.index) == 0:
        return pd.DataFrame()

    model = lda.LDA(n_topics=len(sig_prob.columns), random_state=0, n_iter=10000, alpha=0.01)
    model.components_ = sig_prob.values.T

    sample_sig = model.transform(tri_nuc_table.values, max_iter=1000)

    sample_sig = pd.DataFrame(sample_sig, index=tri_nuc_table.index, columns=sig_prob.columns)
    sample_sig.index.name = 'Sample'
    sample_sig.columns = [a[len('Signature '):] for a in sample_sig.columns]
    sample_sig.columns.name = 'Signature'

    return sample_sig


def plot_signature_heatmap(sample_sig):
    if sample_sig.shape[0] <= 1:
        return plt.figure(figsize=(8,5))
    g = seaborn.clustermap(sample_sig, figsize=(8,5))
    g.ax_heatmap.set_yticklabels(g.ax_heatmap.get_yticklabels(), rotation=0)
    return g.fig


def test_ancestral_descendant(data):
    data = dict(list(data.groupby(by=lambda a: a.endswith('Node0'))))
    return scipy.stats.mannwhitneyu(data[True], data[False])[1]


def plot_signature_boxplots(sample_sig, pvalue_threshold=0.01):

    # Show only signatures with p-value less than specified
    test_pvalue = sample_sig.apply(test_ancestral_descendant)
    data = sample_sig.loc[:,test_pvalue[test_pvalue < pvalue_threshold].index]

    data = data.stack()
    data.name = 'Proportion'
    data = data.reset_index()
    data['is_node0'] = data['Sample'].apply(lambda a: a.endswith('Node0'))
    data['Branch'] = data['is_node0'].apply(lambda a: ('Descendant', 'Ancestral')[a])

    sig_order = np.sort(data['Signature'].unique().astype(int)).astype(str)

    g = seaborn.FacetGrid(data, col='Signature', col_order=sig_order, col_wrap=5, margin_titles=True, sharey=False)
    g.map_dataframe(seaborn.boxplot, x='Branch', y='Proportion', fliersize=0., color='0.75')
    g.map_dataframe(seaborn.stripplot, x='Branch', y='Proportion', jitter=True, color='k',
        linewidth=0, split=False)

    for signature, ax in zip(g.col_names, g.axes):
        ax.set_title('Signature {0}\n  (p = {1:.1e})'.format(signature, test_pvalue.loc[signature]))
        yticks = ax.get_yticks()
        ax.set_yticks(yticks[yticks >= 0.])

    new_xticklabels = list()
    for label in (a.get_text() for a in g.axes[0].get_xticklabels()):
        n = len(data.loc[data['Branch'] == label, 'Sample'].unique())
        label = '{}\nn={}'.format(label, n)
        new_xticklabels.append(label)
    g.axes[0].set_xticklabels(new_xticklabels)

    seaborn.despine(offset=10, trim=True)

    plt.tight_layout()

    return g.fig


def load_signature_probabilities():
    """ Load a dataframe of cosmic signature probabilities.
    """
    sig_prob_filename = pkg_resources.resource_filename('wgs_analysis', 'data/signatures_probabilities.tsv')

    sig_prob = pd.read_csv(sig_prob_filename, sep='\t')

    sig_prob['tri_nucleotide_context'] = sig_prob['Trinucleotide']
    sig_prob['tri_nuc_idx'] = range(len(sig_prob.index))
    sig_prob['ref'] = sig_prob['Substitution Type'].apply(lambda a: a.split('>')[0])
    sig_prob['alt'] = sig_prob['Substitution Type'].apply(lambda a: a.split('>')[1])

    # Original
    sig1 = sig_prob[['tri_nuc_idx', 'ref', 'alt', 'tri_nucleotide_context']].copy()

    # Reverse complement
    sig2 = sig_prob[['tri_nuc_idx', 'ref', 'alt', 'tri_nucleotide_context']].copy()
    for col in ['ref', 'alt', 'tri_nucleotide_context']:
        sig2[col] = sig2[col].apply(reverse_complement)

    # Signatures in terms of ref and alt
    sigs = pd.concat([sig1, sig2], ignore_index=True)

    # Probability matrix
    signature_cols = filter(lambda a: a.startswith('Signature'), sig_prob.columns)
    sig_prob = sig_prob.set_index('tri_nuc_idx')[signature_cols]

    return sigs, sig_prob


def plot_cohort_mutation_signatures(
    sig_prob_filename,
    snvs_table,
    snv_nodes_table,
):
    """ Plot cohort wide clone specific mutation signatures.

    Args:
        sig_prob_filename (str): cosmic signature probability matrix
        snvs_table (pandas.DataFrame): table of per snv information including Trinucleotide
        snv_nodes_table (pandas.DataFrame): table of per snv per clone information

    """
    sigs, sig_prob = load_signature_probabilities()

    results = {}

    #
    # Per sample signatures
    #

    snvs_table = snvs_table[snvs_table['tri_nucleotide_context'].notnull()]
    snvs_table = snvs_table.merge(sigs)

    # Simple filter for variant sample presence
    snvs_table = snvs_table[snvs_table['alt_counts'] > 0]

    snvs_table['patient_sample_id'] = snvs_table['patient_id'] + '_' + snvs_table['sample_id']
    sample_sig = fit_sample_signatures(snvs_table, sig_prob, 'patient_sample_id')

    results['samples_table'] = sample_sig.copy()
    results['samples_heatmap'] = plot_signature_heatmap(sample_sig)

    #
    # Per node signatures
    #

    # Tri nucleotides from snvs table
    cohort_tri_nuc = snvs_table[['chrom', 'coord', 'ref', 'alt', 'tri_nuc_idx']].drop_duplicates()
    snv_nodes_table = snv_nodes_table.merge(cohort_tri_nuc)

    snv_nodes_table['patient_node_id'] = snv_nodes_table['patient_id'] + '_Node' + snv_nodes_table['node'].astype(str)
    node_sig = fit_sample_signatures(snv_nodes_table, sig_prob, 'patient_node_id')

    results['node_table'] = node_sig.copy()
    results['node_heatmap'] = plot_signature_heatmap(node_sig)
    results['node_signature_boxplots'] = plot_signature_boxplots(node_sig)

    return results
