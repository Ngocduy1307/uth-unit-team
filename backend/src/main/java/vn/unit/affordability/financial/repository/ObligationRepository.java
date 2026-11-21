package vn.unit.affordability.financial.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.financial.model.Obligation;

import java.util.List;

@Repository
public interface ObligationRepository extends JpaRepository<Obligation, String> {

    List<Obligation> findByDossierId(String dossierId);

    List<Obligation> findByDossierIdAndIsIncludedInDtiTrue(String dossierId);
}
