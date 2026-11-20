package vn.unit.affordability.financial.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.financial.model.AffordabilitySnapshot;

import java.util.List;
import java.util.Optional;

@Repository
public interface AffordabilitySnapshotRepository extends JpaRepository<AffordabilitySnapshot, String> {

    List<AffordabilitySnapshot> findByDossierIdOrderBySnapshotVersionDesc(String dossierId);

    Optional<AffordabilitySnapshot> findByDossierIdAndSnapshotVersion(String dossierId, Integer snapshotVersion);
}
