package vn.unit.affordability.dossier.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.dossier.model.EvidenceOcrResult;

import java.util.List;
import java.util.Optional;

@Repository
public interface EvidenceOcrResultRepository extends JpaRepository<EvidenceOcrResult, String> {

    List<EvidenceOcrResult> findByEvidenceIdOrderByOcrVersionDesc(String evidenceId);

    Optional<EvidenceOcrResult> findFirstByEvidenceIdOrderByOcrVersionDesc(String evidenceId);

    Optional<EvidenceOcrResult> findByEvidenceIdAndOcrVersion(String evidenceId, Integer ocrVersion);

    List<EvidenceOcrResult> findByDossierIdOrderByCreatedAtDesc(String dossierId);
}
