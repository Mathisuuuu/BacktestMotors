"""Flux : ce que le VOLUME dit du prix.

Le depot porte deja `obv@1` et `vwap@1`. Ce module ajoute la famille des
indicateurs de flux monetaire, dont le principe commun est de ponderer le
deplacement du prix par le volume qui l'a accompagne.

Une mise en garde vaut pour tout le module. Sur des contrats a terme, le
volume d'une serie continue `.v.0` saute au roulement : l'ancienne echeance se
vide, la nouvelle se remplit. Un indicateur de flux lit ce saut comme un
evenement de marche. Les series du depot ne sont pas ajustees au roulement
([[reference/donnees]]) ; ces primitives sont utilisables, mais leurs pics au
voisinage d'un roulement sont un artefact, pas un signal.

Comme partout dans le depot, les cumuls sont bornes par une FENETRE. Un cumul
depuis l'origine remonterait tout l'historique : son cout dependrait de la
position dans l'echantillon et son warmup serait indefinissable - c'est le
motif deja inscrit au ledger pour `obv@1` et pour le noeud `cumulative`.
"""

from __future__ import annotations

from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import FloatArray, ema_serie, securise, sma_serie
from rsl.primitives.builtin.oscillateurs import LineOutput, PairParams
from rsl.primitives.registry import primitive


class FluxParams(WindowParams):
    """Fenetre de cumul d'un indicateur de flux."""


class AdOscParams(WindowParams):
    """Deux fenetres, ou `window` est la LENTE et `fast_window` la rapide.

    L'ordre n'est pas celui de `PairParams` (`window` rapide, `slow_window`
    lente), et c'est delibere. Une machine qui lit le squelette remplit le
    champ obligatoire `window` avec un entier quelconque ; si `window` etait la
    rapide et la lente un defaut fige a 10, toute valeur >= 10 serait refusee.
    En faisant de `window` la LENTE et de la rapide un petit defaut, n'importe
    quelle fenetre raisonnable fonctionne du premier coup.

    Defaut trouve par `test_skeleton.py::test_chaque_primitive_se_construit_avec_ses_defauts`,
    qui construit chaque primitive comme le ferait une machine.
    """

    fast_window: int = 3
    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.fast_window < 1:
            raise ValueError(f"fast_window doit etre >= 1, recu {self.fast_window}")
        if self.fast_window >= self.window:
            raise ValueError(
                f"fast_window ({self.fast_window}) doit etre < window "
                f"({self.window}) : sinon la rapide est la lente"
            )
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class KlingerParams(PairParams):
    """Klinger : deux EMA du volume signe, plus une ligne de signal."""


def _clv(
    hauts: FloatArray, bas: FloatArray, clotures: FloatArray
) -> FloatArray:
    """Position de la cloture dans la barre, de -1 a +1.

    Les barres sans amplitude donnent 0 - ici c'est correct et non une
    invention : une barre plate n'apporte ni accumulation ni distribution, et
    sa contribution au cumul doit etre nulle.
    """
    amplitudes = hauts - bas
    sortie: FloatArray = np.zeros(amplitudes.shape, dtype=np.float64)
    utiles = amplitudes > 0.0
    sortie[utiles] = (
        (clotures[utiles] - bas[utiles]) - (hauts[utiles] - clotures[utiles])
    ) / amplitudes[utiles]
    return sortie


def _adosc_warmup(params: PrimitiveParams) -> int:
    return cast("AdOscParams", params).lookback


def _klinger_warmup(params: PrimitiveParams) -> int:
    reglages = cast("KlingerParams", params)
    return reglages.lookback + reglages.signal_window + 1


@primitive(
    "ad",
    version=1,
    params=FluxParams,
    warmup=window_warmup(),
    summary="Ligne d'accumulation / distribution cumulee sur la FENETRE.",
)
def ad(ctx: Context, params: FluxParams) -> float | None:
    """Volume pondere par la position de la cloture dans sa barre.

    L'idee : une cloture haute dans la barre signale de l'accumulation, une
    cloture basse de la distribution, et le volume dit avec quelle conviction.

    Cumulee sur la fenetre et non depuis l'origine, pour la raison inscrite au
    ledger. Consequence pratique : la valeur n'est pas comparable a celle
    d'une plateforme qui cumule depuis le premier jour - seule sa VARIATION
    l'est.
    """
    fenetre = params.window
    clv = _clv(
        ctx.values(Field.HIGH, fenetre),
        ctx.values(Field.LOW, fenetre),
        ctx.values(Field.CLOSE, fenetre),
    )
    return float(np.sum(clv * ctx.values(Field.VOLUME, fenetre)))


@primitive(
    "adosc",
    version=1,
    params=AdOscParams,
    warmup=_adosc_warmup,
    summary="Oscillateur de Chaikin : EMA rapide moins EMA lente de la ligne A/D.",
)
def adosc(ctx: Context, params: AdOscParams) -> float | None:
    """Derivee de la ligne A/D, qui en supprime le niveau arbitraire.

    C'est ce qui le rend preferable a `ad@1` en pratique : le niveau d'une
    ligne cumulee depend de l'origine du cumul, sa DERIVEE non.
    """
    besoin = params.lookback
    clv = _clv(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    ligne = np.cumsum(clv * ctx.values(Field.VOLUME, besoin))
    rapide = float(ema_serie(ligne, params.fast_window)[-1])
    lente = float(ema_serie(ligne, params.window)[-1])
    return rapide - lente


@primitive(
    "cmf",
    version=1,
    params=FluxParams,
    warmup=window_warmup(),
    summary="Chaikin Money Flow : flux A/D rapporte au volume total, de -1 a 1.",
)
def cmf(ctx: Context, params: FluxParams) -> float | None:
    """`ad@1` normalise par le volume de la fenetre, donc borne et comparable.

    Sa borne `[-1, 1]` est ce qui en fait un indicateur lisible la ou `ad@1`
    ne l'est pas : un seuil de 0,2 a le meme sens sur ES et sur CL.
    """
    fenetre = params.window
    clv = _clv(
        ctx.values(Field.HIGH, fenetre),
        ctx.values(Field.LOW, fenetre),
        ctx.values(Field.CLOSE, fenetre),
    )
    volumes = ctx.values(Field.VOLUME, fenetre)
    return securise(float(np.sum(clv * volumes)), float(np.sum(volumes)))


@primitive(
    "mfi",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Money Flow Index : un RSI pondere par le volume, de 0 a 100.",
)
def mfi(ctx: Context, params: FluxParams) -> float | None:
    """RSI dont chaque variation est pesee par le flux monetaire.

    Le flux est `prix_typique * volume`, et le sens vient de la variation du
    prix typique d'une barre a l'autre. Une divergence entre `mfi@1` et
    `rsi@1` dit que le mouvement se fait a volume faible - c'est le seul usage
    ou il apporte quelque chose qu'un RSI ne donne pas.
    """
    besoin = params.window + 1
    typiques = (
        ctx.values(Field.HIGH, besoin)
        + ctx.values(Field.LOW, besoin)
        + ctx.values(Field.CLOSE, besoin)
    ) / 3.0
    flux = typiques * ctx.values(Field.VOLUME, besoin)
    variations = np.diff(typiques)
    positifs = float(np.sum(flux[1:][variations > 0.0]))
    negatifs = float(np.sum(flux[1:][variations < 0.0]))
    return securise(100.0 * positifs, positifs + negatifs)


@primitive(
    "eom",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Ease of Movement : deplacement du prix par unite de volume, lisse.",
)
def eom(ctx: Context, params: FluxParams) -> float | None:
    """« Combien de volume a-t-il fallu pour bouger le prix ? »

    Eleve quand le prix monte facilement, negatif quand il descend facilement,
    proche de zero quand il faut beaucoup de volume pour peu de mouvement.
    L'echelle brute est immense - le volume est au denominateur - donc c'est un
    indicateur a lire en signe et en tendance, pas en niveau.
    """
    besoin = params.window + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    volumes = ctx.values(Field.VOLUME, besoin)

    medians = (hauts + bas) / 2.0
    deplacements = np.diff(medians)
    amplitudes = hauts[1:] - bas[1:]
    volumes_utiles = volumes[1:]

    valides = (volumes_utiles > 0.0) & (amplitudes > 0.0)
    if not np.any(valides):
        return None
    ratios = amplitudes[valides] / volumes_utiles[valides]
    return float(np.mean(deplacements[valides] * ratios))


@primitive(
    "force_index",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Indice de force d'Elder : variation du prix multipliee par le volume.",
)
def force_index(ctx: Context, params: FluxParams) -> float | None:
    """Le produit le plus direct entre direction et conviction.

    En unites de prix multipliees par du volume : non comparable entre
    instruments, et pas normalisable sans choisir arbitrairement par quoi
    diviser. Publie tel quel plutot que faussement normalise.
    """
    besoin = params.window + 1
    clotures = ctx.values(Field.CLOSE, besoin)
    volumes = ctx.values(Field.VOLUME, besoin)
    forces = np.diff(clotures) * volumes[1:]
    return float(np.mean(forces))


@primitive(
    "pvt",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Price Volume Trend : volume pondere par le rendement, cumule sur la fenetre.",
)
def pvt(ctx: Context, params: FluxParams) -> float | None:
    """Variante d'`obv@1` qui pese le volume par l'AMPLITUDE du mouvement.

    `obv@1` ajoute le volume entier des qu'une barre monte, quelle que soit la
    hausse. Celui-ci le pondere par le rendement, donc une hausse de 0,01 %
    compte cent fois moins qu'une hausse de 1 %.
    """
    besoin = params.window + 1
    clotures = ctx.values(Field.CLOSE, besoin)
    volumes = ctx.values(Field.VOLUME, besoin)
    precedentes = clotures[:-1]
    if np.any(precedentes <= 0.0):
        return None
    rendements = (clotures[1:] - precedentes) / precedentes
    return float(np.sum(rendements * volumes[1:]))


@primitive(
    "nvi",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Negative Volume Index : rendement cumule des seules barres a volume EN BAISSE.",
)
def nvi(ctx: Context, params: FluxParams) -> float | None:
    """Suit le prix uniquement quand le volume DIMINUE.

    L'hypothese de Fosback : l'argent avise agit dans le calme, la foule dans
    l'agitation. Le NVI suivrait donc l'argent avise. C'est une hypothese, pas
    un fait mesure - et elle a ete formulee sur des actions, pas sur des
    contrats a terme.

    Exprime en pourcentage cumule sur la fenetre, et non en indice base 1000
    depuis l'origine, pour la meme raison que `ad@1`.
    """
    besoin = params.window + 1
    clotures = ctx.values(Field.CLOSE, besoin)
    volumes = ctx.values(Field.VOLUME, besoin)
    precedentes = clotures[:-1]
    if np.any(precedentes <= 0.0):
        return None
    rendements = 100.0 * (clotures[1:] - precedentes) / precedentes
    calmes = np.diff(volumes) < 0.0
    return float(np.sum(rendements[calmes]))


@primitive(
    "pvi",
    version=1,
    params=FluxParams,
    warmup=window_warmup(1),
    summary="Positive Volume Index : rendement cumule des seules barres a volume EN HAUSSE.",
)
def pvi(ctx: Context, params: FluxParams) -> float | None:
    """Le miroir de `nvi@1` : ce que fait le prix quand la foule participe.

    Les deux se lisent ENSEMBLE. Pris isolement, aucun des deux ne dit grand
    chose ; leur ecart dit si le mouvement recent s'est fait dans le calme ou
    dans l'agitation.
    """
    besoin = params.window + 1
    clotures = ctx.values(Field.CLOSE, besoin)
    volumes = ctx.values(Field.VOLUME, besoin)
    precedentes = clotures[:-1]
    if np.any(precedentes <= 0.0):
        return None
    rendements = 100.0 * (clotures[1:] - precedentes) / precedentes
    agitees = np.diff(volumes) > 0.0
    return float(np.sum(rendements[agitees]))


@primitive(
    "pvo",
    version=1,
    params=PairParams,
    warmup=lambda p: cast("PairParams", p).lookback + cast("PairParams", p).signal_window,
    summary="Percentage Volume Oscillator : le MACD applique au volume.",
)
def pvo(ctx: Context, params: PairParams) -> float | None:
    """Detecte une acceleration du VOLUME, sans regarder le prix.

    Utile comme filtre : n'entrer que si la participation s'accelere. Il ne
    porte aucune information directionnelle - le volume n'a pas de signe.
    """
    besoin = params.lookback + params.signal_window
    volumes = ctx.values(Field.VOLUME, besoin)
    rapide = ema_serie(volumes, params.window)
    lente = ema_serie(volumes, params.slow_window)
    commun = min(rapide.size, lente.size)
    if commun < params.signal_window:
        return None
    base = lente[-commun:]
    if np.any(base <= 0.0):
        return None
    ligne = 100.0 * (rapide[-commun:] - base) / base
    signal = float(ema_serie(ligne, params.signal_window)[-1])
    if params.output is LineOutput.LINE:
        return float(ligne[-1])
    if params.output is LineOutput.SIGNAL:
        return signal
    return float(ligne[-1]) - signal


@primitive(
    "volume_oscillator",
    version=1,
    params=AdOscParams,
    warmup=window_warmup(),
    summary="Ecart relatif entre volume moyen court et volume moyen long, en %.",
)
def volume_oscillator(ctx: Context, params: AdOscParams) -> float | None:
    """Version a moyennes SIMPLES de `pvo@1`, plus lisible et sans amorce.

    Preferable quand on veut un filtre de participation dont on puisse
    verifier la valeur a la main.
    """
    volumes = ctx.values(Field.VOLUME, params.window)
    court = float(np.mean(volumes[-params.fast_window :]))
    long = float(np.mean(volumes))
    return securise(100.0 * (court - long), long)


@primitive(
    "klinger",
    version=1,
    params=KlingerParams,
    warmup=_klinger_warmup,
    summary="Oscillateur de Klinger : volume SIGNE par la tendance, doublement lisse.",
)
def klinger(ctx: Context, params: KlingerParams) -> float | None:
    """Volume affecte d'un signe selon le sens du prix typique, puis lisse.

    La version d'origine pondere par une « force » calculee a partir du
    mouvement cumule de la seance. Cette version-la suppose une notion de
    seance que la primitive n'a pas - c'est le role du noeud `session`. Ce qui
    est calcule ici est la variante simplifiee et la plus repandue : le volume
    signe, lisse par deux EMA.
    """
    besoin = params.lookback + params.signal_window + 1
    typiques = (
        ctx.values(Field.HIGH, besoin)
        + ctx.values(Field.LOW, besoin)
        + ctx.values(Field.CLOSE, besoin)
    ) / 3.0
    volumes = ctx.values(Field.VOLUME, besoin)
    signes = np.sign(np.diff(typiques))
    signes[signes == 0.0] = 1.0
    volume_signe = signes * volumes[1:]

    rapide = ema_serie(volume_signe, params.window)
    lente = ema_serie(volume_signe, params.slow_window)
    commun = min(rapide.size, lente.size)
    if commun < params.signal_window:
        return None
    ligne = rapide[-commun:] - lente[-commun:]
    if params.output is LineOutput.LINE:
        return float(ligne[-1])
    signal = float(sma_serie(ligne, params.signal_window)[-1])
    if params.output is LineOutput.SIGNAL:
        return signal
    return float(ligne[-1]) - signal


@primitive(
    "dollar_volume",
    version=1,
    params=FluxParams,
    warmup=window_warmup(),
    summary="Volume en valeur : prix typique fois volume, moyenne sur la fenetre.",
)
def dollar_volume(ctx: Context, params: FluxParams) -> float | None:
    """La mesure de LIQUIDITE, celle qui sert a filtrer un univers.

    Le volume en contrats ne se compare pas entre instruments : 1 000 lots de
    ES ne pesent pas 1 000 lots de CL. Multiplie par le prix, il devient un
    montant - et deux marches deviennent comparables.

    Attention : le multiplicateur du contrat n'est PAS applique ici, la
    primitive ne connait pas l'instrument. Le montant est donc a un facteur
    constant pres, ce qui suffit pour un classement mais pas pour une
    comparaison absolue entre contrats de multiplicateurs differents.
    """
    fenetre = params.window
    typiques = (
        ctx.values(Field.HIGH, fenetre)
        + ctx.values(Field.LOW, fenetre)
        + ctx.values(Field.CLOSE, fenetre)
    ) / 3.0
    return float(np.mean(typiques * ctx.values(Field.VOLUME, fenetre)))
