package vn.unit.affordability.dossier.service;

import vn.unit.affordability.dossier.dto.CreateEvidenceRequest;
import vn.unit.affordability.dossier.dto.EvidenceOcrResultResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.SubmitOcrResultRequest;

import java.util.List;

public interface EvidenceService {

    EvidenceRecordResponse registerEvidence(String dossierId, CreateEvidenceRequest request);

    List<EvidenceRecordResponse> getEvidencesByDossierId(String dossierId, boolean latestOnly);

    EvidenceRecordResponse getEvidenceById(String evidenceId);

    EvidenceOcrResultResponse submitOcrResult(String evidenceId, SubmitOcrResultRequest request);

    List<EvidenceOcrResultResponse> getOcrResultsByEvidenceId(String evidenceId);

    EvidenceOcrResultResponse getLatestOcrResult(String evidenceId);
}
