package vn.unit.affordability.dossier.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.dossier.model.EvidenceRecord;

import java.util.List;
import java.util.Optional;

@Repository
public interface EvidenceRecordRepository extends JpaRepository<EvidenceRecord, String> {

    List<EvidenceRecord> findByDossierId(String dossierId);

    Optional<EvidenceRecord> findByFileHash(String fileHash);
}
