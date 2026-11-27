package vn.unit.affordability.dossier.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.dossier.model.EvidenceRecord;

import java.util.List;
import java.util.Optional;

@Repository
public interface EvidenceRecordRepository extends JpaRepository<EvidenceRecord, String> {

    List<EvidenceRecord> findByDossierIdOrderByCreatedAtDesc(String dossierId);

    List<EvidenceRecord> findByDossierIdAndIsLatestTrueOrderByCreatedAtDesc(String dossierId);

    List<EvidenceRecord> findByDossierIdAndFileTypeOrderByVersionDesc(String dossierId, String fileType);

    Optional<EvidenceRecord> findByDossierIdAndFileHash(String dossierId, String fileHash);

    Optional<EvidenceRecord> findByFileHash(String fileHash);
}
