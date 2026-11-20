package vn.unit.affordability.dossier.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.unit.affordability.dossier.dto.CreateDossierRequest;
import vn.unit.affordability.dossier.dto.DossierResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.UpdateDossierStatusRequest;
import vn.unit.affordability.dossier.model.Dossier;
import vn.unit.affordability.dossier.model.EvidenceRecord;
import vn.unit.affordability.dossier.repository.DossierRepository;
import vn.unit.affordability.dossier.repository.EvidenceRecordRepository;
import vn.unit.affordability.shared.exception.BusinessValidationException;
import vn.unit.affordability.shared.exception.ResourceNotFoundException;

import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class DossierService {

    private final DossierRepository dossierRepository;
    private final EvidenceRecordRepository evidenceRecordRepository;

    @Transactional
    public DossierResponse createDossier(CreateDossierRequest request) {
        if (dossierRepository.existsByApplicationId(request.getApplicationId())) {
            throw new BusinessValidationException("Application ID already exists: " + request.getApplicationId());
        }
        Dossier dossier = Dossier.builder()
                .id(UUID.randomUUID().toString())
                .applicationId(request.getApplicationId())
                .applicantId(request.getApplicantId())
                .applicantName(request.getApplicantName())
                .bankCode(request.getBankCode())
                .makerId(request.getMakerId())
                .loanProduct(request.getLoanProduct())
                .requestedAmount(request.getRequestedAmount())
                .requestedTenorMonths(request.getRequestedTenorMonths())
                .proposedInterestRate(request.getProposedInterestRate())
                .monthlyDeclaredLivingExpense(request.getMonthlyDeclaredLivingExpense())
                .build();
        return toResponse(dossierRepository.save(dossier));
    }

    public DossierResponse getDossierById(String id) {
        return dossierRepository.findById(id)
                .map(this::toResponse)
                .orElseThrow(() -> new ResourceNotFoundException("Dossier not found: " + id));
    }

    public List<DossierResponse> getDossiersByApplicantId(String applicantId) {
        return dossierRepository.findByApplicantId(applicantId)
                .stream()
                .map(this::toResponse)
                .toList();
    }

    public List<DossierResponse> getDossiersByStatus(String status) {
        return dossierRepository.findByStatus(status)
                .stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public DossierResponse updateStatus(String id, UpdateDossierStatusRequest request) {
        Dossier dossier = dossierRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Dossier not found: " + id));
        dossier.setStatus(request.getStatus());
        if (request.getCheckerId() != null) {
            dossier.setCheckerId(request.getCheckerId());
        }
        return toResponse(dossierRepository.save(dossier));
    }

    public List<EvidenceRecordResponse> getEvidencesByDossierId(String dossierId) {
        if (!dossierRepository.existsById(dossierId)) {
            throw new ResourceNotFoundException("Dossier not found: " + dossierId);
        }
        return evidenceRecordRepository.findByDossierId(dossierId)
                .stream()
                .map(this::toEvidenceResponse)
                .toList();
    }

    private DossierResponse toResponse(Dossier d) {
        return DossierResponse.builder()
                .id(d.getId())
                .applicationId(d.getApplicationId())
                .applicantId(d.getApplicantId())
                .applicantName(d.getApplicantName())
                .bankCode(d.getBankCode())
                .status(d.getStatus())
                .makerId(d.getMakerId())
                .checkerId(d.getCheckerId())
                .analysisDate(d.getAnalysisDate())
                .loanProduct(d.getLoanProduct())
                .requestedAmount(d.getRequestedAmount())
                .requestedTenorMonths(d.getRequestedTenorMonths())
                .proposedInterestRate(d.getProposedInterestRate())
                .monthlyDeclaredLivingExpense(d.getMonthlyDeclaredLivingExpense())
                .createdAt(d.getCreatedAt())
                .updatedAt(d.getUpdatedAt())
                .build();
    }

    private EvidenceRecordResponse toEvidenceResponse(EvidenceRecord e) {
        return EvidenceRecordResponse.builder()
                .id(e.getId())
                .dossierId(e.getDossierId())
                .fileName(e.getFileName())
                .fileHash(e.getFileHash())
                .fileType(e.getFileType())
                .storagePath(e.getStoragePath())
                .status(e.getStatus())
                .uploadedBy(e.getUploadedBy())
                .fileSizeBytes(e.getFileSizeBytes())
                .mimeType(e.getMimeType())
                .ocrStatus(e.getOcrStatus())
                .ocrProcessedAt(e.getOcrProcessedAt())
                .createdAt(e.getCreatedAt())
                .build();
    }
}
