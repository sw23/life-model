# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Dict, List, TypeVar, Generic, TYPE_CHECKING
from abc import ABC, abstractmethod

if TYPE_CHECKING:
    from .people.person import Person

T = TypeVar('T')


class Registry(Generic[T], ABC):
    """Abstract base class for registries that manage relationships between entities"""

    def __init__(self):
        self._items: Dict[str, List[T]] = {}

    @abstractmethod
    def _get_key(self, owner: 'Person') -> str:
        """Get the unique key for an owner"""
        pass

    def register(self, owner: 'Person', item: T) -> None:
        """Register an item for an owner"""
        key = self._get_key(owner)
        if key not in self._items:
            self._items[key] = []
        self._items[key].append(item)

    def unregister(self, owner: 'Person', item: T) -> bool:
        """Unregister an item for an owner. Returns True if item was found and removed"""
        key = self._get_key(owner)
        if key in self._items and item in self._items[key]:
            self._items[key].remove(item)
            if not self._items[key]:
                del self._items[key]
            return True
        return False

    def get_items(self, owner: 'Person') -> List[T]:
        """Get all items for an owner"""
        key = self._get_key(owner)
        return self._items.get(key, [])

    def clear(self, owner: 'Person') -> None:
        """Clear all items for an owner"""
        key = self._get_key(owner)
        if key in self._items:
            del self._items[key]

    def get_all_items(self) -> List[T]:
        """Get all items across all owners"""
        all_items = []
        for items in self._items.values():
            all_items.extend(items)
        return all_items


class PersonRegistry(Registry[T]):
    """Registry that uses Person's unique_id as the key"""

    def _get_key(self, owner: 'Person') -> str:
        return str(owner.unique_id)


class BankAccountRegistry(PersonRegistry['BankAccount']):
    """Registry for managing BankAccount relationships"""
    pass


class JobRegistry(PersonRegistry['Job']):
    """Registry for managing Job relationships"""
    pass


class HomeRegistry(PersonRegistry['Home']):
    """Registry for managing Home relationships"""
    pass


class ApartmentRegistry(PersonRegistry['Apartment']):
    """Registry for managing Apartment relationships"""
    pass


class LifeInsuranceRegistry(PersonRegistry['LifeInsurance']):
    """Registry for managing LifeInsurance policy relationships"""
    pass


class GeneralInsuranceRegistry(PersonRegistry['Insurance']):
    """Registry for managing general Insurance policy relationships"""
    pass


class AnnuityRegistry(PersonRegistry['Annuity']):
    """Registry for managing Annuity relationships"""
    pass


class ModelRegistries:
    """Container for all registries in a model"""

    def __init__(self):
        self.bank_accounts = BankAccountRegistry()
        self.jobs = JobRegistry()
        self.homes = HomeRegistry()
        self.apartments = ApartmentRegistry()
        self.life_insurance_policies = LifeInsuranceRegistry()
        self.general_insurance_policies = GeneralInsuranceRegistry()
        self.annuities = AnnuityRegistry()

    def clear_all(self, owner: 'Person') -> None:
        """Clear all registries for a specific owner"""
        self.bank_accounts.clear(owner)
        self.jobs.clear(owner)
        self.homes.clear(owner)
        self.apartments.clear(owner)
        self.life_insurance_policies.clear(owner)
        self.general_insurance_policies.clear(owner)
        self.annuities.clear(owner)
