# vim: set fileencoding=utf-8
""" 
SQLAlchemy object model for fundamental OFX data aggregates such as transactions, 
balances, and securities.
"""
# 3rd party imports
from sqlalchemy import (
    Column,
    Boolean,
    Enum,
    Integer,
    String,
    Text,
    ForeignKey,
    ForeignKeyConstraint,
    )
import sqlalchemy.types
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.ext.declarative import (
    declarative_base,
    as_declarative,
    declared_attr,
    has_inherited_table,
    )
from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
    relationship,
    backref,
    )
from sqlalchemy.orm.exc import NoResultFound

# local imports
from types import Numeric, OFXDateTime
from ofxtools.lib import LANG_CODES, CURRENCY_CODES, COUNTRY_CODES


# Enums used in aggregate validation
INV401KSOURCES = ('PRETAX', 'AFTERTAX', 'MATCH', 'PROFITSHARING',
                    'ROLLOVER', 'OTHERVEST', 'OTHERNONVEST')
ACCTTYPES = ('CHECKING', 'SAVINGS', 'MONEYMRKT', 'CREDITLINE')
INVSUBACCTS = ('CASH', 'MARGIN', 'SHORT', 'OTHER')
BUYTYPES = ('BUY', 'BUYTOCOVER')
SELLTYPES = ('SELL', 'SELLSHORT')
INCOMETYPES = ('CGLONG', 'CGSHORT', 'DIV', 'INTEREST', 'MISC')
ASSETCLASSES = ('DOMESTICBOND', 'INTLBOND', 'LARGESTOCK', 'SMALLSTOCK',
                'INTLSTOCK', 'MONEYMRKT', 'OTHER')


# DB setup
# We need a session for Aggregate.get() to construct queries and
# Aggregate.get_or_create() to add transient instances
DBSession = scoped_session(sessionmaker())


# Object classes
@as_declarative()
class Aggregate(object):
    """
    Declarative mixin of OFX 'aggregate', i.e. SGML parent node that contains
    no data.

    Aggregates are grouped into higher-order containers such as lists
    and statements.  Although such higher-order containers are 'aggregates'
    per the OFX specification, they are represented here by their own Python
    classes other than Aggregate.
    """
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    @classmethod
    def primary_keys(cls):
        return [c.name for c in cls.__table__.c if c.primary_key]

    @classmethod
    def get(cls, **attrs):
        pks = cls.primary_keys()
        try:
            pk = {k: attrs[k] for k in pks}
        except KeyError:
            msg = "%s: Required attributes %s not satisfied by arguments %s" % (
                cls.__name__, pks, attrs)
            raise ValueError(msg)
        instance = DBSession.query(cls).filter_by(**pk).one()
        return instance

    @classmethod
    def get_or_create(cls, **attrs):
        """
        Return existing instance with matching PK if it exists, else create
        an instance with all attrs given in keywords and return it.
        """
        try:
            instance = cls.get(**attrs)
        except NoResultFound:
            instance = cls(**attrs)
            DBSession.add(instance)
        return instance
    
    @classmethod
    def from_etree(cls, element, **extra_attrs):
        """ 
        Look up the Aggregate subclass for a given ofx.Parser.Element and
        feed it the Element to instantiate the Aggregate instance.
        """
        get_or_create = extra_attrs.pop('get_or_create', False)
        SubClass = globals()[element.tag]
        element, extra_attrs = SubClass._preflatten(element, **extra_attrs)
        attributes = element._flatten()
        attributes, extra_attrs = SubClass._postflatten(attributes, **extra_attrs)
        attributes.update(extra_attrs)

        if get_or_create:
            instance = SubClass.get_or_create(**attributes)
        else:
            instance = SubClass(**attributes)
        return instance

    @classmethod
    def _preflatten(cls, element, **extra_attrs):
        """ 
        Hook for subclasses to preprocess incoming SGML data before flattening
        elements and instantiation.
        """
        return element, extra_attrs

    @classmethod
    def _postflatten(cls, element, **extra_attrs):
        """ 
        Hook for subclasses to preprocess incoming SGML data after flattening
        elements but before instantiation.
        """
        return element, extra_attrs

    def __repr__(self):
        return '<%s(%s)>' % (self.__class__.__name__, ', '.join(
            ['%s=%r' % (c.name, str(getattr(self, c.name))) \
             for c in self.__class__.__table__.c \
             if getattr(self, c.name) is not None]
        ))


def Inheritor(parent_table):
    class InheritanceMixin(object):
        """
        Uses a surrogate primary key to implement joined-table inheritance;
        the natural keys are given as a class attribute 'pks'
        """
        @declared_attr.cascading
        def id(cls): 
            if has_inherited_table(cls):
                return Column(Integer, ForeignKey('%s.id' % parent_table),
                              primary_key=True)
            else:
                return Column(Integer, primary_key=True)

        subclass = Column(String(length=32), nullable=False)

        @declared_attr
        def __mapper_args__(cls):
            if has_inherited_table(cls):
                return {'polymorphic_identity': cls.__name__.lower()}
            else:
                return {'polymorphic_on': cls.subclass}

        @classmethod
        def primary_keys(cls):
            return cls.pks

    return InheritanceMixin


### CURRENCIES
class CURRENCY(object):
    """ Declarative mixin representing OFX <CURRENCY> aggregate """
    cursym = Column(Enum(*CURRENCY_CODES, name='cursym'))
    currate = Column(Numeric())


class ORIGCURRENCY(CURRENCY):
    """ Declarative mixin representing OFX <ORIGCURRENCY> aggregate """
    curtype = Column(Enum('CURRENCY', 'ORIGCURRENCY', name='curtype'))

    @classmethod
    def _do_origcurrency(cls, element, **extra_attrs):
        """ 
        See OFX spec section 5.2 for currency handling conventions.
        Flattening the currency definition leaves only the CURRATE/CURSYM
        elements, leaving no indication of whether these were sourced from
        a CURRENCY aggregate or ORIGCURRENCY.  Since this distinction is
        important to interpreting transactions in foreign correncies, we
        preserve this information by adding a nonstandard curtype element.
        """
        currency = element.find('*/CURRENCY')
        origcurrency = element.find('*/ORIGCURRENCY')
        if (currency is not None) and (origcurrency is not None):
            raise ValueError("<%s> may not contain both <CURRENCY> and \
                             <ORIGCURRENCY>" % elem.tag)
        curtype = currency
        if curtype is None:
            curtype = origcurrency
        if curtype is not None:
            curtype = curtype.tag
        extra_attrs['curtype'] = curtype

        return element, extra_attrs


### ACCOUNTS
class ACCTFROM(Inheritor('acctfrom'), Aggregate):
    """ 
    Synthetic base class of {BANK,CC,INV}ACCTFROM - not in OFX spec. 
    """
    # Extra attribute definitions not from OFX spec
    name = Column(Text)


class BANKACCTFROM(ACCTFROM):
    bankid = Column(String(length=9), nullable=False)
    branchid = Column(String(length=22))
    acctid = Column(String(length=22), nullable=False)
    accttype = Column(Enum(*ACCTTYPES, name='accttype'), nullable=False)
    acctkey = Column(String(length=22))

    pks = ['bankid', 'acctid', ]
    __table_args__ = (UniqueConstraint(*pks),)


class CCACCTFROM(ACCTFROM):
    # Elements from OFX spec
    acctid = Column(String(length=22), nullable=False)
    acctkey = Column(String(length=22))

    pks = ['acctid', ]
    __table_args__ = (UniqueConstraint(*pks),)


class INVACCTFROM(ACCTFROM):
    # Elements from OFX spec
    brokerid = Column(String(length=22), nullable=False)
    acctid = Column(String(length=22), nullable=False)

    pks = ['brokerid', 'acctid']
    __table_args__ = (UniqueConstraint(*pks),)


class ACCTTO(Inheritor('acctto'), Aggregate):
    """ 
    Synthetic base class of {BANK,CC,INV}ACCTTO - not in OFX spec. 
    """
    # Extra attribute definitions not from OFX spec
    name = Column(Text)


class BANKACCTTO(ACCTTO):
    # Elements from OFX spec
    bankid = Column(String(length=9), nullable=False)
    branchid = Column(String(length=22))
    acctid = Column(String(length=9), nullable=False)
    accttype = Column(Enum(*ACCTTYPES, name='accttype'), nullable=False)
    acctkey = Column(String(length=22))

    pks = ['bankid', 'acctid', ]
    __table_args__ = (UniqueConstraint(*pks),)


class CCACCTTO(ACCTTO):
    # Elements from OFX spec
    acctid = Column(String(length=22), nullable=False, unique=True)
    acctkey = Column(String(length=22))

    pks = ['acctid', ]
    __table_args__ = (UniqueConstraint(*pks),)


### BALANCES
class Balance(object):
    """
    Declarative mixin holding object model common to OFX *BAL aggregates.

    We deviate from the OFX spec by storing the STMT.dtasof in *BAL.dtasof
    in order to uniquely link the balance with the statement without 
    persisting a STMT object. We make *BAL.dtasof mandatory and use it
    as part of the primary key.
    """
    @declared_attr
    def acctfrom_id(cls):
        return Column(Integer, ForeignKey('acctfrom.id'), primary_key=True)

    @declared_attr
    def acctfrom(cls):
        return relationship('ACCTFROM', backref='%ss' % cls.__name__.lower())

    @declared_attr
    def dtasof(cls):
        return Column(OFXDateTime, primary_key=True)


class LEDGERBAL(Balance, Aggregate):
    balamt = Column(Numeric(), nullable=False)


class AVAILBAL(Balance, Aggregate):
    balamt = Column(Numeric(), nullable=False)


class INVBAL(Balance, Aggregate):
    availcash = Column(Numeric(), nullable=False)
    marginbalance = Column(Numeric(), nullable=False)
    shortbalance = Column(Numeric(), nullable=False)
    buypower = Column(Numeric())


class BAL(Balance, CURRENCY, Aggregate):
    name = Column(String(length=32), primary_key=True)
    desc = Column(String(length=80), nullable=False)
    baltype = Column(Enum('DOLLAR', 'PERCENT', 'NUMBER', name='baltype'),
                     nullable=False)
    value = Column(Numeric(), nullable=False)


### SECURITIES
class SECID(object):
    """
    Mixin to hold logic for securities-related investment transactions (INVTRAN)
    and also OPTINFO
    """
    @declared_attr
    def secinfo_id(cls):
        return Column(Integer, ForeignKey('secinfo.id'))

    @declared_attr
    def secinfo(cls):
        return relationship('SECINFO')

    @classmethod
    def _do_secid(cls, element, **extra_attrs):
        """ 
        Replace SECID with FK reference to existing SECINFO
        """
        secid = element.find('.//SECID')
        uniqueidtype = secid.find('UNIQUEIDTYPE')
        uniqueid = secid.find('UNIQUEID')
        secinfo = SECINFO.get(uniqueidtype=uniqueidtype.text,
                              uniqueid=uniqueid.text)
        extra_attrs['secinfo_id'] = secinfo.id
        # SECID appears either under INV{BUY,SELL} or else directly under 
        # the parent transaction.
        # We can use XPath to find SECID anywhere in the aggregate, but
        # ElementTree doesn't let us find its parent cheaply, so we just
        # remove its elements and let _flatten() erase the SECID aggregate.
        secid.remove(uniqueidtype)
        secid.remove(uniqueid)
        return element, extra_attrs


class SECINFO(Inheritor('secinfo'), CURRENCY, Aggregate):
    uniqueidtype = Column(String(length=10), nullable=False)
    uniqueid = Column(String(length=32), nullable=False)
    # FIs *cough* IBKR *cough* abuse SECNAME/TICKER with too much information
    # Relaxing the length constraints from the OFX spec does little harm
    #secname = Column(String(length=120), nullable=False)
    secname = Column(String(length=255), nullable=False)
    #ticker = Column(String(length=32))
    ticker = Column(String(length=255))
    fiid = Column(String(length=32))
    rating = Column(String(length=10))
    unitprice = Column(Numeric())
    dtasof = Column(OFXDateTime)
    memo = Column(String(length=255))

    pks = ['uniqueid', 'uniqueidtype']
    __table_args__ = (UniqueConstraint(*pks),)
   

class DEBTINFO(SECINFO):
    parvalue = Column(Numeric(), nullable=False)
    debttype = Column(Enum('COUPON', 'ZERO', name='debttype'), nullable=False)
    debtclass = Column(Enum('TREASURY', 'MUNICIPAL', 'CORPORATE', 'OTHER',
                           name='debtclass')
                      )
    couponrt = Column(Numeric())
    dtcoupon = Column(OFXDateTime)
    couponfreq = Column(Enum('MONTHLY', 'QUARTERLY', 'SEMIANNUAL', 'ANNUAL',
                            'OTHER', name='couponfreq')
                       )
    callprice = Column(Numeric())
    yieldtocall = Column(Numeric())
    dtcall = Column(OFXDateTime)
    calltype = Column(Enum('CALL', 'PUT', 'PREFUND', 'MATURITY', 
                           name='calltype')
                     )
    ytmat = Column(Numeric())
    dtmat = Column(OFXDateTime)
    assetclass = Column(Enum(*ASSETCLASSES, name='assetclass'))
    fiassetclass = Column(String(length=32))


class MFINFO(SECINFO):
    mftype = Column(Enum('OPENEND', 'CLOSEEND', 'OTHER', name='mftype'))
    yld = Column(Numeric())
    dtyieldasof = Column(OFXDateTime)

    @classmethod
    def from_etree(cls, elem, **extra_attrs):
        """ 
        Strip MFASSETCLASS/FIMFASSETCLASS - lists that will blow up _flatten()
        Replace *ASSETCLASS lists with *PORTIONs having FK references to MFINFO
        """
        mfassetclasses = []

        # Do all XPath searches before removing nodes from the tree
        #   which seems to mess up the DOM in Python3 and throw an
        #   AttributeError on subsequent searches.
        mfassetclass = elem.find('./MFASSETCLASS')
        fimfassetclass = elem.find('./FIMFASSETCLASS')

        if mfassetclass is not None:
            # Convert PORTIONs; save for later
            mfassetclasses.append(mfassetclass)
            elem.remove(mfassetclass)
        if fimfassetclass is not None:
            # Convert FIPORTIONs; save for later
            mfassetclass.append(fimfassetclass)
            elem.remove(fimfassetclass)

        instance = Aggregate.from_etree(elem, **extra_attrs)

        # Instantiate MFASSETCLASS/FIMFASSETCLASS with foreign key reference
        # to MFINFO
        for mfassetclass in mfassetclasses:
            for portion in mfassetclass:
                p = Aggregate.from_etree(
                    portion, mfinfo_id=instance.id,
                    get_or_create=True
                )

        return instance


class PORTION(Aggregate):
    # Added for SQLAlchemy object model
    mfinfo_id = Column(Integer, ForeignKey('mfinfo.id'), primary_key=True)
    mfinfo = relationship('MFINFO', backref='mfassetclasses')

    # Elements from OFX spec
    assetclass = Column(
        Enum(*ASSETCLASSES, name='assetclass'), primary_key=True
    )
    percent = Column(Numeric(), nullable=False)


class FIPORTION(Aggregate):
    # Added for SQLAlchemy object model
    mfinfo_id = Column(Integer, ForeignKey('mfinfo.id'), primary_key=True)
    mfinfo = relationship('MFINFO', backref='fimfassetclasses')

    # Elements from OFX spec
    fiassetclass = Column(
        Enum(*ASSETCLASSES, name='assetclass'), primary_key=True
    )
    percent = Column(Numeric(), nullable=False)


class OPTINFO(SECINFO):
    opttype = Column(Enum('CALL', 'PUT', name='opttype'), nullable=False)
    strikeprice = Column(Numeric(), nullable=False)
    dtexpire = Column(OFXDateTime, nullable=False)
    shperctrct = Column(Integer, nullable=False)
    assetclass = Column(Enum(*ASSETCLASSES, name='assetclass'))
    fiassetclass = Column(String(length=32))

    @classmethod
    def _preflatten(cls, element, **extra_attrs):
        element, extra_attrs = cls._do_secid(element, **extra_attrs)
        return element, extra_attrs

    @classmethod
    def _do_secid(cls, element, **extra_attrs):
        """ 
        A <SECID> aggregate referring to the security underlying the option
        is, in general, *not* going to be contained in <SECLIST> (because you
        don't necessarily have a position in the underlying).  Since the <SECID>
        for the underlying only gives us fields for (uniqueidtype, uniqueid) 
        we can't really go ahead and use this information to create a 
        corresponding SECINFO instance (since we lack information about the
        security subclass).  It's not clear that the SECID of the underlying is 
        really needed for anything, so we disregard it.
        """
        secid = element.find('./SECID')
        if secid is not None:
            element.remove(secid)
        return element, extra_attrs


class OTHERINFO(SECINFO):
    typedesc = Column(String(length=32))
    assetclass = Column(Enum(*ASSETCLASSES, name='assetclass'))
    fiassetclass = Column(String(length=32))
    percent = Column(Numeric())


class STOCKINFO(SECINFO):
    typedesc = Column(String(length=32))
    stocktype = Column(Enum('COMMON', 'PREFERRED', 'CONVERTIBLE', 'OTHER',
                           name='stocktype')
                      )
    # 'yield' is a reserved word in Python
    yld = Column(Numeric())
    dtyieldasof = Column(OFXDateTime)
    typedesc = Column(String(length=32))
    assetclass = Column(Enum(*ASSETCLASSES, name='assetclass'))
    fiassetclass = Column(String(length=32))

    @classmethod
    def _postflatten(cls, attributes, **extra_attrs):
        # Rename 'yield' (a reserved word in Python) to 'yld'
        yld = attributes.pop('yield', None)
        if yld:
            attributes['yld'] = yld
        return attributes, extra_attrs


### TRANSACTIONS
class PAYEE(Aggregate):
    # Elements from OFX spec
    name = Column(String(length=32), primary_key=True)
    addr1 = Column(String(length=32), nullable=False)
    addr2 = Column(String(length=32))
    addr3 = Column(String(length=32))
    city = Column(String(length=32), nullable=False)
    state = Column(String(length=5), nullable=False)
    postalcode = Column(String(length=11), nullable=False)
    country = Column(Enum(*COUNTRY_CODES, name='country'))
    phone = Column(String(length=32), nullable=False)


class BANKTRAN(ORIGCURRENCY):
    """ 
    Synthetic mixin for common elements of STMTTRN/INVBANKTRAN - not in OFX spec
    """
    # Added for SQLAlchemy object model
    @declared_attr
    def acctto_id(cls):
        return Column(Integer, ForeignKey('acctto.id'))

    @declared_attr
    def acctto(cls):
        return relationship('ACCTTO')

    @declared_attr
    def payee_name(cls):
        return Column(String(32), ForeignKey('payee.name'))

    @declared_attr
    def payee(cls):
        return relationship('PAYEE')

    # Elements from OFX spec
    fitid = Column(String(length=255), primary_key=True)
    srvrtid = Column(String(length=10))
    trntype = Column(Enum('CREDIT', 'DEBIT', 'INT', 'DIV', 'FEE', 'SRVCHG',
                    'DEP', 'ATM', 'POS', 'XFER', 'CHECK', 'PAYMENT',
                    'CASH', 'DIRECTDEP', 'DIRECTDEBIT', 'REPEATPMT',
                    'OTHER', name='trntype'), nullable=False)
    dtposted = Column(OFXDateTime, nullable=False)
    dtuser = Column(OFXDateTime)
    dtavail = Column(OFXDateTime)
    trnamt = Column(Numeric(), nullable=False)
    correctfitid = Column(Numeric())
    correctaction = Column(Enum('REPLACE', 'DELETE', name='correctaction'))
    checknum = Column(String(length=12))
    refnum = Column(String(length=32))
    sic = Column(Integer())
    payeeid = Column(String(length=12))
    name = Column(String(length=32))
    memo = Column(String(length=255))
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))

    @classmethod
    def _preflatten(cls, element, **extra_attrs):
        """
        Replace BANKACCTTO/CCACCTTO/PAYEE with FK references.

        This is needed for {BANK,CC}ACCTTO because account type information is
        contained in the aggregate container, which will be lost by _flatten().

        PAYEE will not lose information when _flatten()ed, but it really needs
        its own object class to be useful to an application.
        """
        # BANKACCTTO/CCACCTTO
        bankacctto = element.find('BANKACCTTO')
        if bankacctto:
            instance = Aggregate.from_etree(bankacctto, get_or_create=True)
            extra_attrs['acctto_id'] = instance.id
            element.remove(instance)
        else:
            ccacctto = element.find('CCACCTTO')
            if ccacctto:
                instance = Aggregate.from_etree(ccacctto, get_or_create=True)
                extra_attrs['acctto_id'] = instance.id
                element.remove(ccacctto)
        # PAYEE
        payee = element.find('PAYEE')
        if payee:
            instance = Aggregate.from_etree(payee, get_or_create=True)
            extra_attrs['payee_name'] = instance.name
            element.remove(payee)

        return element, extra_attrs


class STMTTRN(BANKTRAN, Aggregate):
     # Added for SQLAlchemy object model
    acctfrom_id = Column(Integer, ForeignKey('acctfrom.id'), primary_key=True)
    acctfrom = relationship('ACCTFROM', foreign_keys=[acctfrom_id,], backref='stmttrns')


class INVBANKTRAN(BANKTRAN, Aggregate):
    # Added for SQLAlchemy object model
    acctfrom_id = Column(Integer, ForeignKey('invacctfrom.id'), primary_key=True)
    acctfrom = relationship('INVACCTFROM')

    # Elements from OFX spec
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'), nullable=False)


class INVTRAN(Inheritor('invtran'), Aggregate):
    # Added for SQLAlchemy object model
    @declared_attr
    def acctfrom_id(cls):
        return Column(Integer, ForeignKey('invacctfrom.id'))
    
    @declared_attr
    def acctfrom(cls):
        return relationship('INVACCTFROM', backref='invtrans')

    subclass = Column(String(length=32), nullable=False)

    # Elements from OFX spec
    fitid = Column(String(length=255))
    srvrtid = Column(String(length=10))
    dttrade = Column(OFXDateTime, nullable=False)
    dtsettle = Column(OFXDateTime)
    reversalfitid = Column(String(length=255))
    memo = Column(String(length=255))


    pks = ['acctfrom_id', 'fitid']
    __table_args__ = (UniqueConstraint(*pks),)

    @classmethod
    def _preflatten(cls, element, **extra_attrs):
        element, extra_attrs = cls._do_secid(element, **extra_attrs)
        element, extra_attrs = cls._do_origcurrency(element, **extra_attrs)
        return element, extra_attrs

    classmethod
    def _do_secid(cls, element, **extra_attrs):
        """ Hook for processing SECID in subclass """
        return element, extra_attrs

    @classmethod
    def _do_origcurrency(cls, element, **extra_attrs):
        """ Hook for processing ORIGCURRENCY in subclass """
        return element, extra_attrs


class INVBUYSELL(SECID, ORIGCURRENCY):
    """ Synthetic base class of INVBUY/INVSELL - not in OFX spec """
    units = Column(Numeric(), nullable=False)
    unitprice = Column(Numeric(), nullable=False)
    commission = Column(Numeric())
    taxes = Column(Numeric())
    fees = Column(Numeric())
    load = Column(Numeric())
    total = Column(Numeric(), nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'))
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'))
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class INVBUY(INVBUYSELL):
    """ Declarative mixin for OFX INVBUY aggregate """
    markup = Column(Numeric())
    loanid = Column(String(length=32))
    loanprincipal = Column(Numeric())
    loaninterest = Column(Numeric())
    dtpayroll = Column(OFXDateTime)
    prioryearcontrib = Column(Boolean())


class INVSELL(INVBUYSELL):
    """ Declarative mixin for OFX INVSELL aggregate """
    markdown = Column(Numeric())
    withholding = Column(Numeric())
    taxexempt = Column(Boolean())
    gain = Column(Numeric())
    loanid = Column(String(length=32))
    statewithholding = Column(Numeric())
    penalty = Column(Numeric())


class BUYDEBT(INVBUY, INVTRAN):
    accrdint = Column(Numeric())


class BUYMF(INVBUY, INVTRAN):
    buytype = Column(Enum(*BUYTYPES, name='buytype'), nullable=False)
    relfitid = Column(String(length=255))


class BUYOPT(INVBUY, INVTRAN):
    optbuytype = Column(Enum('BUYTOOPEN', 'BUYTOCLOSE', name='obtbuytype'),
                        nullable=False
                       )
    shperctrct = Column(Integer, nullable=False)


class BUYOTHER(INVBUY, INVTRAN):
    pass


class BUYSTOCK(INVBUY, INVTRAN):
    buytype = Column(Enum(*BUYTYPES, name='buytype'), nullable=False)


class CLOSUREOPT(SECID, INVTRAN):
    optaction = Column(Enum('EXERCISE', 'ASSIGN', 'EXPIRE', name='optaction'))
    units = Column(Numeric(), nullable=False)
    shperctrct = Column(Integer, nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    relfitid = Column(String(length=255))
    gain = Column(Numeric())
    

class INCOME(SECID, ORIGCURRENCY, INVTRAN):
    incometype = Column(Enum(*INCOMETYPES, name='incometype'), nullable=False)
    total = Column(Numeric(), nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'), nullable=False)
    taxexempt = Column(Boolean())
    withholding = Column(Numeric())
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class INVEXPENSE(SECID, ORIGCURRENCY, INVTRAN):
    total = Column(Numeric(), nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'), nullable=False)
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class JRNLFUND(INVTRAN):
    subacctto = Column(Enum(*INVSUBACCTS, name='subacctto'), nullable=False)
    subacctfrom = Column(Enum(*INVSUBACCTS, name='subacctfrom'), nullable=False)
    total = Column(Numeric(), nullable=False)


class JRNLSEC(SECID, INVTRAN):
    subacctto = Column(Enum(*INVSUBACCTS, name='subacctto'), nullable=False)
    subacctfrom = Column(Enum(*INVSUBACCTS, name='subacctfrom'), nullable=False)
    units = Column(Numeric(), nullable=False)


class MARGININTEREST(ORIGCURRENCY, INVTRAN):
    total = Column(Numeric(), nullable=False)
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'), nullable=False)


class REINVEST(SECID, ORIGCURRENCY, INVTRAN):
    incometype = Column(Enum(*INCOMETYPES, name='incometype'), nullable=False)
    total = Column(Numeric(), nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'))
    units = Column(Numeric(), nullable=False)
    unitprice = Column(Numeric(), nullable=False)
    commission = Column(Numeric())
    taxes = Column(Numeric())
    fees = Column(Numeric())
    load = Column(Numeric())
    taxexempt = Column(Boolean())
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class RETOFCAP(SECID, ORIGCURRENCY, INVTRAN):
    total = Column(Numeric(), nullable=False)
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'), nullable=False)
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class SELLDEBT(INVSELL, INVTRAN):
    sellreason = Column(Enum('CALL', 'SELL', 'MATURITY', name='sellreason'),
                        nullable=False
                       )
    accrdint = Column(Numeric())


class SELLMF(INVSELL, INVTRAN):
    selltype = Column(Enum(*SELLTYPES, name='selltype'), nullable=False)
    avgcostbasis = Column(Numeric())
    relfitid = Column(String(length=255))


class SELLOPT(INVSELL, INVTRAN):
    optselltype = Column(Enum('SELLTOCLOSE', 'SELLTOOPEN', name='optselltype'),
                         nullable=False)
    shperctrct = Column(Integer, nullable=False)
    relfitid = Column(String(length=255))
    reltype = Column(Enum('SPREAD', 'STRADDLE', 'NONE', 'OTHER', name='reltype')
                    )
    secured = Column(Enum('NAKED', 'COVERED', name='secured'))


class SELLOTHER(INVSELL, INVTRAN):
    pass


class SELLSTOCK(INVSELL, INVTRAN):
    selltype = Column(Enum(*SELLTYPES, name='selltype'), nullable=False)


class SPLIT(SECID, INVTRAN):
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    oldunits = Column(Numeric(), nullable=False)
    newunits = Column(Numeric(), nullable=False)
    numerator = Column(Numeric(), nullable=False)
    denominator = Column(Numeric(), nullable=False)
    fraccash = Column(Numeric())
    subacctfund = Column(Enum(*INVSUBACCTS, name='subacctfund'))
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


class TRANSFER(SECID, INVTRAN):
    subacctsec = Column(Enum(*INVSUBACCTS, name='subacctsec'), nullable=False)
    units = Column(Numeric(), nullable=False)
    tferaction = Column(Enum('IN', 'OUT', name='tferaction'), nullable=False)
    postype = Column(Enum('SHORT', 'LONG', name='postype'), nullable=False)
    avgcostbasis = Column(Numeric())
    unitprice = Column(Numeric())
    dtpurchase = Column(OFXDateTime)
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))


### POSITIONS
class INVPOS(Inheritor('invpos'), SECID, CURRENCY, Aggregate):
    # Added for SQLAlchemy object model
    acctfrom_id = Column(Integer, ForeignKey('invacctfrom.id'))
    acctfrom = relationship('INVACCTFROM', backref='invposs')
    dtasof = Column(OFXDateTime)

    pks = ['acctfrom_id', 'secinfo_id', 'dtasof']
    __table_args__ = (UniqueConstraint(*pks),)

    # Elements from OFX spec
    heldinacct = Column(Enum(*INVSUBACCTS, name='heldinacct'), nullable=False)
    postype = Column(Enum('SHORT', 'LONG', name='postype'), nullable=False)
    units = Column(Numeric(), nullable=False)
    unitprice = Column(Numeric(), nullable=False)
    mktval = Column(Numeric(), nullable=False)
    dtpriceasof = Column(OFXDateTime, nullable=False)
    memo = Column(String(length=255))
    inv401ksource = Column(Enum(*INV401KSOURCES, name='inv401ksource'))
  
    @classmethod
    def _preflatten(cls, element, **extra_attrs):
        element, extra_attrs = cls._do_secid(element, **extra_attrs)
        return element, extra_attrs


class POSDEBT(INVPOS):
    pass


class POSMF(INVPOS):
    unitsstreet = Column(Numeric())
    unitsuser = Column(Numeric())
    reinvdiv = Column(Boolean())
    reinvcg = Column(Boolean())


class POSOPT(INVPOS):
    secured = Column(Enum('NAKED', 'COVERED', name='secured'))


class POSOTHER(INVPOS):
    pass

class POSSTOCK(INVPOS):
    unitsstreet = Column(Numeric())
    unitsuser = Column(Numeric())
    reinvdiv = Column(Boolean())

